"""Spanish presentation view models. No policy decisions or simulation writes."""
from __future__ import annotations

from collections import deque
import time
import numpy as np

TURTLE_MESSAGE = 'Ninguna tortuga saldrá lastimada durante esta simulación.'
ZONE_LABELS = {'SAFE': 'SEGURA', 'CAUTION': 'PRECAUCIÓN', 'AVOID': 'EVITAR', 'CLOSED': 'CERRADA'}
WIND_LABELS = {'N': 'NORTE', 'NE': 'NORESTE', 'E': 'ESTE', 'SE': 'SURESTE',
               'S': 'SUR', 'SW': 'SUROESTE', 'W': 'OESTE', 'NW': 'NOROESTE'}
STATE_LABELS = {'WAITING_SAFE': 'ESPERANDO', 'WAITING_UNSAFE': 'ESPERANDO',
                'EVACUATING': 'EVACUANDO', 'REASSIGNING': 'EVACUANDO',
                'AT_MEETING_AREA': 'EN ZONA SEGURA', 'INCAPACITATED': 'INCAPACITADO'}
CONTROLS = 'A — Iniciar emergencia    ESPACIO — Pausa    + / − — Velocidad    V — Cambiar viento    H — Humo    D — Detalles'


def level(value, limits, names=('BAJO', 'MEDIO', 'ALTO')):
    return names[0] if value < limits[0] else names[1] if value < limits[1] else names[2]


def presentation_data(center):
    """Four disjoint pupil categories; meeting presence is not certified safety."""
    counts = dict(safe=0, evacuating=0, inside=0, incapacitated=0)
    for p in center.people:
        if center.tracker.records[p.person_id].level == 'incapacitada':
            counts['incapacitated'] += 1
        elif p.building_id is not None:
            counts['inside'] += 1
        elif (center.router.at_meeting(p) and center.router.safe.get(center.router.assignments[p.person_id][0], False)
              and center.router.area_policy.states[center.router.assignments[p.person_id][0]] in ('SAFE', 'CAUTION')):
            counts['safe'] += 1
        else:
            counts['evacuating'] += 1
    cfg = center.config['presentation']
    smoky = int(np.count_nonzero(np.asarray(center.environment.smoke.concentrations) >= cfg['smoke_count_threshold']))
    return dict(**counts, mode='INTELIGENTE' if center.decision_policy else 'TRADICIONAL',
        wind=WIND_LABELS[center.direction], speed=level(center.intensity, cfg['wind_speed_thresholds'], ('LENTO', 'MEDIO', 'RÁPIDO')),
        fire=level(len(center.environment.fire.burning), cfg['fire_level_cells']),
        smoke=level(smoky, cfg['smoke_level_cells']),
        available=sum(a.enabled and center.router.area_policy.states[a.area_id] in ('SAFE', 'CAUTION') for a in center.areas),
        total_areas=len(center.areas))


def student_lines(center, pid):
    p = center.manager.get_person(pid)
    exposure = center.tracker.records[pid]
    state = ('INCAPACITATED' if exposure.level == 'incapacitada' else center.metrics.states.get(pid, 'WAITING_SAFE'))
    assignment = center.router.assignments.get(pid)
    destination = 'Zona '+assignment[0] if assignment and assignment[0] in center.router.areas else 'Buscando zona segura'
    reason = center.router.pending_reasons.get(pid)
    translated = {'imminent_fire': 'fuego cercano', 'current_danger': 'peligro',
                  'meeting_closed': 'zona cerrada', 'toxic_dose': 'humo',
                  'predicted_destination': 'riesgo previsto', 'future_destination': 'riesgo previsto',
                  'temporal_route': 'riesgo previsto', 'watchdog': 'peligro'}
    detail = ('Motivo: '+translated[reason] if reason in translated else
              'Dentro del edificio' if p.building_id else 'En el campus')
    return ['Alumno', 'Estado: '+STATE_LABELS.get(state, 'EVACUANDO'), 'Destino: '+destination, detail]


def debug_student_data(center, pid):
    """Read-only telemetry when Traditional has no personal decision policy."""
    from simulation.personal_safety import toxic_dose_eta
    p = center.manager.get_person(pid)
    x, y = p.position
    hazard, risk = center.hazard_arrival, center.risk_field
    dose = toxic_dose_eta(center.tracker.records[pid], risk.smoke[y, x], risk.predicted_smoke[y, x],
                          center.config['personal_safety'], dose_limit=center.config['personal_safety']['dose_limit'])
    return dict(state=center.metrics.states.get(pid, 'WAITING_SAFE'), fire_eta=hazard.time_to_fire(x, y),
                smoke_eta=hazard.time_to_smoke(x, y), toxic_dose_eta=dose, safety_margin=None, priority=None)


class PresentationMessages:
    """Aggregate deltas once per turn; wall-clock TTL, at most three messages."""
    def __init__(self, config):
        self.config = config
        self.items = deque(maxlen=config['maximum_messages'])
        self.session = None
        self.previous = {}
        self.turn = -1

    def observe(self, center, now=None):
        now = time.monotonic() if now is None else now
        if self.session != center.run_id:
            self.session = center.run_id; self.items.clear(); self.previous = {}; self.turn = -1
        turn = center.environment.fire.turn
        if turn != self.turn:
            router = center.router
            values = {'routes': router.replanned_routes, 'zones': sum(e['from'] in router.areas and e['to'] in router.areas for e in router.destination_changes),
                      'doors': len(center.controller.blocked_exit_groups) if center.controller else 0,
                      'refuge': center.controller.predictive.actions['interior_refuge']
                        if center.controller and center.controller.predictive else 0}
            for key, text in [('routes', '{} alumnos ajustaron su ruta para evacuar'),
                              ('zones', '{} alumnos cambiaron de zona por riesgo'),
                              ('doors', 'Salida bloqueada: buscando otra'),
                              ('refuge', 'Alumnos alejándose del incendio dentro del edificio')]:
                delta = values[key]-self.previous.get(key, values[key])
                if delta > 0:
                    message = text.format(delta)
                    self.items = deque((e for e in self.items if e[2] != key), maxlen=self.config['maximum_messages'])
                    self.items.append((now, message, key))
            self.previous = values; self.turn = turn
        while self.items and now-self.items[0][0] > self.config['message_lifetime_seconds']:
            self.items.popleft()
        return [e[1] for e in self.items]
