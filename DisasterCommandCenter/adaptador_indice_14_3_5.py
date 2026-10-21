"""PASO 14.3.5 - adaptador OPT-IN para pruebas en copia aislada.

NO modifica ni sustituye los módulos src/simulation/*.
Usar únicamente con una instancia controlada por este adaptador.

Aviso: los controladores 8.12/12 modifican posiciones interiores directamente.
Por eso se reconstruye el índice al finalizar CADA paso, incluso paso manual.
Cambios externos directos de Person.x/y requieren rebuild_index() explicito.
"""
from __future__ import annotations

from indexed_indoor_people import IndexedIndoorPersonManager
from simulation.evacuation_control import EvacuationControlCenter
from simulation.hazard_impact import ExposureTracker, FireEvacuationControlCenter
from simulation.person import Person


class _IndexedCenterMixin:
    """Integra el índice por instancia sin parchear métodos globales."""

    def reset(self):
        super().reset()
        original = self.people
        indexado = IndexedIndoorPersonManager.from_json(self.campus_path)
        for p in original:
            indexado.add_person(Person(
                p.person_id, p.x, p.y, p.status, p.speed, p.building_id
            ))
        indexado.assert_index_consistent()
        self.manager = indexado
        self.people = indexado.list_people()
        # El tracker del Paso 12 almacena registros vinculados al conjunto
        # de personas de la instancia de la simulación.
        if isinstance(self, FireEvacuationControlCenter):
            self.tracker = ExposureTracker(self.people)
        self.log = [self._sample()]

    def step(self, *, manual: bool = False):
        try:
            return super().step(manual=manual)
        finally:
            # Incluso tras error o paso manual: no dejar índice viejo.
            # No se cambia el estado original de las personas.
            self.manager.rebuild_index()


class IndexedEvacuationControlCenter(_IndexedCenterMixin, EvacuationControlCenter):
    """Versión opt-in de EvacuationControlCenter."""


class IndexedFireEvacuationControlCenter(_IndexedCenterMixin, FireEvacuationControlCenter):
    """Versión opt-in de FireEvacuationControlCenter."""
