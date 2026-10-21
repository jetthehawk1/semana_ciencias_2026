"""Movimiento autonomo local para Disaster Command Center (Paso 8.8).

No calcula rutas de evacuacion. Cada persona camina por celdas vecinas
transitables, sin colisiones, reutilizando PersonManager.move_person().
La velocidad de Person se interpreta aqui como CELDAS POR SEGUNDO.
El motor no depende de Pygame y puede probarse por separado.
"""

from __future__ import annotations

import math
import random


DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))
MAX_STEPS_PER_UPDATE = 6


class AutoMovementController:
    def __init__(self, manager, person_ids=None, seed=2026):
        self.manager = manager
        self.ids = list(person_ids if person_ids is not None else manager.people.keys())
        if not self.ids or len(self.ids) != len(set(self.ids)):
            raise ValueError("Se necesitan IDs de personas unicos y no vacios.")
        if any(manager.get_person(pid) is None for pid in self.ids):
            raise ValueError("Hay IDs que no estan registrados en PersonManager.")
        self.rng = random.Random(seed)
        self.paused = False
        self.time_scale = 1.0
        self.total_moves = 0
        self.moves_by_person = {pid: 0 for pid in self.ids}
        self._credit = {pid: 0.0 for pid in self.ids}
        self._heading = {pid: self.rng.choice(DIRECTIONS) for pid in self.ids}
        self._priority = 0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def set_time_scale(self, value):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0.25 <= value <= 4.0):
            raise ValueError("La velocidad global debe estar entre x0.25 y x4.00.")
        self.time_scale = float(value)

    def _attempt_step(self, pid):
        # Seguir en la misma direccion es mas probable que girar sin motivo.
        heading = self._heading[pid]
        options = list(DIRECTIONS)
        self.rng.shuffle(options)
        if self.rng.random() < 0.78:
            options.remove(heading)
            options.insert(0, heading)

        for dx, dy in options:
            try:
                self.manager.move_person(pid, dx, dy)
            except ValueError:
                # Celdas bloqueadas, ocupadas o limites: probar otro vecino.
                continue
            self._heading[pid] = (dx, dy)
            return True
        return False  # Sin salidas validas: permanecer en la celda actual.

    def update(self, dt_seconds):
        """Avanza la simulacion dt segundos. Retorna numero de pasos reales.

        Los turnos se rotan para evitar favorecer siempre al mismo ID.
        Toda comprobacion de colisiones ocurre en PersonManager.move_person.
        """
        if (isinstance(dt_seconds, bool)
                or not isinstance(dt_seconds, (int, float))
                or not math.isfinite(dt_seconds)
                or dt_seconds < 0):
            raise ValueError("dt_seconds debe ser un numero finito no negativo.")
        if self.paused or dt_seconds == 0:
            return 0

        for pid in self.ids:
            person = self.manager.get_person(pid)
            if person is None:
                raise ValueError(f"La persona {pid} ya no esta en el manager.")
            if person.status == "a_salvo":
                self._credit[pid] = 0.0
                continue
            if not math.isfinite(person.speed) or person.speed <= 0:
                raise ValueError(f"Velocidad invalida para {pid}.")
            self._credit[pid] = min(
                float(MAX_STEPS_PER_UPDATE),
                self._credit[pid] + dt_seconds * person.speed * self.time_scale,
            )

        made = 0
        count = len(self.ids)
        for _ in range(MAX_STEPS_PER_UPDATE):
            ready = False
            for j in range(count):
                pid = self.ids[(self._priority + j) % count]
                if self._credit[pid] + 1e-10 < 1.0:
                    continue
                ready = True
                self._credit[pid] = max(0.0, self._credit[pid] - 1.0)
                if self._attempt_step(pid):
                    self.moves_by_person[pid] += 1
                    made += 1
            self._priority = (self._priority + 1) % count
            if not ready:
                break

        self.total_moves += made
        return made
