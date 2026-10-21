"""Escenario detallado: motores existentes + prioridad y destinos explicitos."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

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


class FunctionalSimulation:
    def __init__(self, root, *, kind="emergencia", mode="original", direction="E", intensity=.75):
        self.root = Path(root)
        data = self.root / "data"
        assets = data / "functional"
        self.config = json.loads((data / "functional_scenario.json").read_text(encoding="utf-8"))
        self.scale = self.config["subdivision"]
        if not 0 < self.config["meeting_smoke_threshold"] < self.config["route_smoke_threshold"] <= 1:
            raise ValueError("Los umbrales de humo deben ser ascendentes entre 0 y 1.")
        if any(type(self.config[k]) is not int or self.config[k] < 1 for k in ("max_routes_per_turn", "retry_after_turns")):
            raise ValueError("Presupuestos de rutas invalidos.")
        self.kind = kind
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
            seed=self.config["seed"], behavior=self.config["fire_behavior"],
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
        self.tracker = ExposureTracker(self.people)
        self.controller = None
        self.phase = "preparado"
        self.moves = 0
        self.selected_ignition = None
        self.last_blocked_cells = set()
        self.areas = load_meeting_areas(self.config, self.manager, {
            (a["exterior_cell"]["x"], a["exterior_cell"]["y"])
            for a in json.loads(self.entrances_path.read_text(encoding="utf-8"))["accesses"]})
        self.router = MeetingRouter(CampusGraph(CampusMap.from_json(assets / "campus.json")),
            self.manager, map_data["name"], self.areas,
            smoke_threshold=self.config["meeting_smoke_threshold"],
            max_routes_per_turn=self.config["max_routes_per_turn"],
            retry_after_turns=self.config["retry_after_turns"])

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
        self.controller = AdaptiveExitController(self.manager, self.entrances_path, manage_exterior=False)
        if self.kind == "emergencia":
            self.environment.ignite(*self.ignition_cell)
        self.building_risk.update(self.environment.fire.burning)
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
        fire = set(self.environment.fire.burning)
        self.environment.step()
        fire.update(self.environment.fire.burning)
        turn = self.environment.fire.turn
        self.wind_history.record(turn)
        concentrations = self.environment.smoke.concentrations
        self.tracker.update(self.people, fire, concentrations)
        self.building_risk.update(fire)
        priorities = self.building_risk.scores(self.origin)
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
        door_hazards = fire | blocked
        moved += self.controller.step_with_hazards(self.tracker, door_hazards, priority_by_person=priorities)
        if isinstance(self.manager, IndexedIndoorPersonManager):
            self.manager.rebuild_index()
        self.moves += moved
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
                "exits": self.controller.exit_metrics() if self.controller else {}}
