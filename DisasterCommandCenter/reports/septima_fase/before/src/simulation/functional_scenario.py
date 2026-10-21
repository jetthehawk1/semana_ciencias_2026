"""Escenario detallado: motores existentes + prioridad y destinos explicitos."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from uuid import uuid4

from indexed_indoor_people import IndexedIndoorPersonManager
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingRouter, load_meeting_areas
from simulation.building_risk import BuildingRisk
from simulation.campus_map import CampusMap
from simulation.hazard_impact import ExposureTracker, HazardEvacuationController
from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor
from simulation.wind_history import WindHistory
from simulation.wind_simulation import WindFireSmokeSimulation
from simulation.exterior_risk import exterior_blocked_cells
from simulation.scenario_fire import ScenarioFireSimulation
from simulation.adaptive_exits import AdaptiveExitController
from simulation.dynamic_risk import DynamicRiskField
from routing.meeting_policy import MeetingAreaPolicy
from integration.wind_telemetry import WindTelemetry
from wind_prediction.model import WindPredictor
from simulation.hazard_arrival import HazardArrivalField
from routing.intelligent_policy import IntelligentEvacuationPolicy
from simulation.evacuation_metrics import EvacuationMetrics


class FunctionalSimulation:
    def __init__(self, root, *, kind="emergencia", mode="original", direction="E", intensity=.75, run_id=None,
                 evacuation_mode=None, seed=None):
        self.root = Path(root)
        data = self.root / "data"
        assets = data / "functional"
        self.config = json.loads((data / "functional_scenario.json").read_text(encoding="utf-8"))
        self.scale = self.config["subdivision"]
        self.evacuation_mode = evacuation_mode or self.config['intelligent_evacuation']['default_mode']
        if self.evacuation_mode not in ('intelligent', 'traditional'):
            raise ValueError('Modo de evacuacion desconocido.')
        if self.evacuation_mode == 'traditional' and not self.config['comparison']['traditional_mode_enabled']:
            raise ValueError('Comparacion Traditional desactivada por configuracion.')
        self.hazard_seed = self.config['seed'] if seed is None else seed
        if not 0 < self.config["meeting_smoke_threshold"] < self.config["route_smoke_threshold"] <= 1:
            raise ValueError("Los umbrales de humo deben ser ascendentes entre 0 y 1.")
        if any(type(self.config[k]) is not int or self.config[k] < 1 for k in ("max_routes_per_turn", "retry_after_turns")):
            raise ValueError("Presupuestos de rutas invalidos.")
        self.kind = kind
        self.run_id = run_id or "dcc_functional_"+uuid4().hex
        self.entrances_path = assets / "building_entrances.json"
        map_data = json.loads((assets / "campus.json").read_text(encoding="utf-8"))
        manager_class = IndexedIndoorPersonManager if mode == "optimizado" else IndoorPersonManager
        self.manager = manager_class(map_data)
        population = json.loads((assets / "population.json").read_text(encoding="utf-8"))
        self.people = IndoorPopulationDistributor(self.manager, self.entrances_path).distribute(
            population["building_counts"], seed=population["seed"])
        self.origin = {p.person_id: p.building_id for p in self.people}
        self.original_counts = Counter(self.origin.values())
        properties = json.loads((assets / "building_properties.json").read_text(encoding="utf-8"))
        fire = ScenarioFireSimulation.from_scenario(assets / "campus.json",
            seed=self.hazard_seed, behavior=self.config["fire_behavior"],
            owners=self.manager.building_owners, properties=properties)
        self.environment = WindFireSmokeSimulation(fire, direction=direction, intensity=intensity,
                                                  **self.config["smoke_behavior"])
        self.direction, self.intensity = direction, intensity
        self.wind_history = WindHistory(direction, intensity,
                                       history_limit=self.config["wind"]["history_limit"])
        properties = json.loads((assets / "building_properties.json").read_text(encoding="utf-8"))
        self.building_risk = BuildingRisk(self.manager.building_owners, properties, scale=self.scale,
            laboratory_radius=self.config["laboratory_policy"]["fire_alert_radius_source_cells"],
            normal_radius=self.config["normal_fire_alert_radius_source_cells"])
        self.risk_field = DynamicRiskField(self.environment.fire.terrain, self.config["risk_routing"],
                                          owners=self.manager.building_owners, properties=properties)
        sensors = json.loads((data / "sensores_paso_13.json").read_text(encoding="utf-8"))["sensors"]
        enabled = set(self.config["wind_telemetry"]["sensor_ids"])
        if not enabled.issubset({s["sensor_id"] for s in sensors}):
            raise ValueError("Sensor de viento inexistente.")
        meteorological = [{**s, "x": s["x"]*self.scale+self.scale//2, "y": s["y"]*self.scale+self.scale//2}
                          for s in sensors if s["sensor_id"] in enabled]
        self.wind_telemetry = WindTelemetry(meteorological, self.run_id,
                                            width=self.manager.width, height=self.manager.height)
        self.wind_predictor = WindPredictor(self.config["wind_prediction"],
                                            self.root / self.config["wind_prediction"]["model_path"])
        self.predicted_wind = None
        self.hazard_arrival = HazardArrivalField(self.environment.fire.terrain, self.config['hazard_arrival'],
                                               self.config['fire_behavior'], self.config['smoke_behavior'])
        self.hazard_arrival.fire_safety = self.config.get('fire_safety')
        self.decision_policy = (IntelligentEvacuationPolicy(self.risk_field, self.hazard_arrival,
            self.config['intelligent_evacuation'], self.config['route_safety'], self.config['meeting_assignment'])
            if self.evacuation_mode == 'intelligent' else None)
        self.tracker = ExposureTracker(self.people)
        if self.decision_policy and 'personal_safety' in self.config:
            p = self.decision_policy
            p.personal_config = self.config['personal_safety']
            p.fire_safety = self.config['fire_safety']
            p.escape_config = self.config['escape_policy']
            p.stability_config = self.config['route_stability']
        self.controller = None
        self.phase = "preparado"
        self.moves = 0
        self.selected_ignition = None
        self.last_blocked_cells = set()
        self.areas = load_meeting_areas(self.config, self.manager, {
            (a["exterior_cell"]["x"], a["exterior_cell"]["y"])
            for a in json.loads(self.entrances_path.read_text(encoding="utf-8"))["accesses"]})
        self.router = MeetingRouter(CampusGraph(CampusMap.from_json(assets / "campus.json")).cache_static_topology(),
            self.manager, map_data["name"], self.areas,
            smoke_threshold=self.config["meeting_smoke_threshold"],
            max_routes_per_turn=self.config["max_routes_per_turn"],
            retry_after_turns=self.config["retry_after_turns"], risk_field=self.risk_field,
            area_policy=MeetingAreaPolicy(self.areas, self.config["meeting_area_policy"], self.config["meeting_smoke_threshold"]),
            decision_policy=self.decision_policy, evacuation_mode=self.evacuation_mode)
        self.router.budget_config = self.config['route_scheduling']
        self.router.exposures = self.tracker.records
        if 'routing_optimization' in self.config:
            self.router.sixth_config = self.config
            if self.config['routing_optimization']['flow_fields_enabled']:
                from routing.meeting_flow import MeetingFlowField
                self.router.flow = MeetingFlowField(self.router.graph)
                self.router.flow.cache_enabled = self.config['routing_optimization']['exact_snapshot_cache']
                self.router.flow.maximum_fields = self.config['routing_optimization']['maximum_flow_fields_per_turn']
        self.fire_contact_traces = []
        self.metrics = EvacuationMetrics(self)

    def _observe_wind(self):
        rows = self.wind_telemetry.sample(self.environment.fire.turn, self.environment.wind)
        self.wind_history.observe(rows)
        self.predicted_wind = self.wind_predictor.predict(list(self.wind_history.measurements))

    def _update_risk(self, fire):
        self.risk_field.update(fire, self.environment.smoke.concentrations, self.environment.wind,
                              self.predicted_wind, turn=self.environment.fire.turn, building_risk=self.building_risk)
        # Also computed in Traditional for symmetric measurement, never decisions.
        if self.config['intelligent_evacuation']['hazard_eta_enabled']:
            self.hazard_arrival.update(self.risk_field, self.environment.wind, self.predicted_wind)
        else:
            self.hazard_arrival.eta.fill(float('inf'))
            self.hazard_arrival.urgency_cost.fill(0)
            self.hazard_arrival.turn = self.environment.fire.turn

    @property
    def ignition_cell(self):
        if self.selected_ignition is not None:
            return self.selected_ignition
        x, y = self.config["ignition_source_cell"]
        return (x*self.scale+self.scale//2, y*self.scale+self.scale//2)

    def select_ignition(self, x, y):
        if self.phase != "preparado" or self.kind != "emergencia":
            raise ValueError("Selecciona el foco antes de iniciar la emergencia.")
        if not self.environment.fire.can_ignite(x, y):
            raise ValueError("Selecciona edificio o vegetacion combustible dentro del mapa.")
        self.selected_ignition = (x, y)
        return self.selected_ignition

    def start_alarm(self):
        if self.phase != "preparado":
            raise ValueError("Reinicia antes de activar otra alarma.")
        self.controller = AdaptiveExitController(self.manager, self.entrances_path, manage_exterior=False,
                                                risk_field=self.risk_field if self.decision_policy else None)
        if self.decision_policy:
            self.controller.safety_policy = self.decision_policy
        if self.kind == "emergencia":
            self.environment.ignite(*self.ignition_cell)
        self._observe_wind()
        self._update_risk(self.environment.fire.burning)
        self.router.assess(self.environment.smoke.concentrations, self.environment.fire.burning)
        if self.evacuation_mode == 'traditional':
            for person in self.people:
                _, outside = self.controller.exit_time(person)
                self.router.fixed_destinations[person.person_id] = min(self.areas, key=lambda a:
                    (max(a.bounds[0]-outside[0], 0, outside[0]-(a.bounds[0]+a.bounds[2]-1))+
                     max(a.bounds[1]-outside[1], 0, outside[1]-(a.bounds[1]+a.bounds[3]-1)), a.area_id)).area_id
        self.phase = "en_curso"

    def toggle_pause(self):
        if self.phase in ("en_curso", "pausado"):
            self.phase = "pausado" if self.phase == "en_curso" else "en_curso"
        return self.phase

    def set_wind(self, direction, intensity):
        self.wind_history.configure(direction, intensity, turn=self.environment.fire.turn)
        self.environment.set_wind(direction, intensity)
        self.direction, self.intensity = direction, intensity

    def ignite(self, x, y):
        if self.phase == "preparado":
            raise ValueError("Activa la alarma antes de anadir fuego.")
        self.environment.ignite(x, y)

    def step(self, *, manual=False):
        if self.phase in ("preparado", "completado") or (self.phase == "pausado" and not manual):
            return 0
        previous = {p.person_id: p.position for p in self.people}
        fire = set(self.environment.fire.burning)
        old_fire = set(fire)
        previous_contacts = {pid for pid,r in self.tracker.records.items() if r.fire_contact}
        self.environment.step()
        fire.update(self.environment.fire.burning)
        turn = self.environment.fire.turn
        self.wind_history.record(turn)
        self._observe_wind()
        concentrations = self.environment.smoke.concentrations
        self.tracker.update(self.people, fire, concentrations)
        for person in self.people:
            pid = person.person_id
            if self.tracker.records[pid].fire_contact and pid not in previous_contacts:
                self.fire_contact_traces.append(dict(turn=turn,person_id=pid,point=person.position,
                    building=person.building_id,source_building=self.origin[pid],
                    category='already_burning_before_turn' if person.position in old_fire else 'fire_reached_occupied_cell_before_movement',
                    prior_diagnostic=self.decision_policy.diagnostics.get(pid) if self.decision_policy else None,
                    route=self.router.assignments.get(pid)))
        self._update_risk(fire)
        self.router.assess(concentrations, fire)
        priorities = self.building_risk.scores(self.origin)
        if self.decision_policy:
            self.decision_policy.predicted_vector = self.predicted_wind.vector
            for person in self.people:
                exposure = self.tracker.records[person.person_id]
                self.decision_policy.inspect(person, self.router, turn, controller=self.controller, exposure=exposure)
                priorities[person.person_id] = self.decision_policy.priority_score(person.person_id,
                    priorities.get(person.person_id, 0), exposure)
        eligible = {p.person_id for p in self.people if p.building_id is None
                    and self.tracker.records[p.person_id].level != "incapacitada"
                    and (self.tracker.records[p.person_id].level != "ralentizada" or self.controller.steps % 2 == 0)}
        blocked = exterior_blocked_cells(fire, concentrations, self.environment.fire.terrain,
            smoke_threshold=self.config["route_smoke_threshold"],
            vegetation_buffer=self.config.get("exterior_fire_buffer_fine_cells", 1))
        self.last_blocked_cells = blocked
        # Exteriores primero. Quien cruza una puerta no se mueve otra vez este turno.
        moved = self.router.advance(concentrations, fire, blocked, priorities, eligible, turn)
        # El cruce interior->exterior respeta la misma mascara del andador.
        immobile = {p.position for p in self.people if self.tracker.records[p.person_id].level == 'incapacitada'}
        door_hazards = fire | blocked | self.router.routing_obstacles | immobile
        if self.decision_policy and self.decision_policy.fire_safety:
            import numpy as np
            ys,xs=np.nonzero(self.hazard_arrival.fire_eta <= self.config['fire_safety']['imminent_margin_turns'])
            door_hazards.update(zip(xs.tolist(),ys.tolist()))
        moved += self.controller.step_with_hazards(self.tracker, door_hazards, priority_by_person=priorities)
        if isinstance(self.manager, IndexedIndoorPersonManager):
            self.manager.rebuild_index()
        self.moves += moved
        self.metrics.sample(self, previous)
        # La simulacion sigue para vigilar/reasignar destinos incluso si todos llegaron.
        return moved

    def summary(self):
        remaining = Counter(p.building_id for p in self.people if p.building_id is not None)
        return {"fase": self.phase, "inicial": len(self.people), "dentro": sum(remaining.values()),
                "salieron": len(self.people)-sum(remaining.values()), "turnos": self.environment.fire.turn,
                "esperando": (self.controller.waiting_last_step if self.controller else 0) + self.router.waiting,
                "movimientos": self.moves, "por_edificio": {
                    name: {"inicial": count, "dentro": remaining[name], "salieron": count-remaining[name]}
                    for name, count in self.original_counts.items()},
                "fuego": self.environment.fire.stats(), "humo": self.environment.smoke.stats(),
                "riesgo": self.tracker.counts(), "viento": {"direccion": self.direction, "intensidad": self.intensity},
                "meeting": self.router.summary(), "building_risk": dict(self.building_risk.levels),
                "exits": self.controller.exit_metrics() if self.controller else {},
                "wind_prediction": (vars(self.predicted_wind) if self.predicted_wind else None),
                "evacuation_mode": self.evacuation_mode,
                "evacuation_states": dict(Counter(self.metrics.states.values())),
                "unsafe_waiting_person_turns": self.metrics.unsafe_waiting_person_turns,
                "confirmed_forecast_departures": len(self.metrics.confirmed_departures),
                "wind_telemetry_records": len(self.wind_telemetry.observations)}
