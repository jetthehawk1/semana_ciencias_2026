"""Riesgo de edificios desde geometria efectiva; usa prioridades de Persona 3."""
from __future__ import annotations

from routing.evacuation_priority import EvacuationPriority


class BuildingRisk:
    def __init__(self, owners, properties, *, scale=3, laboratory_radius=6, normal_radius=2):
        self.properties = properties
        self.scale = scale
        self.laboratory_radius = laboratory_radius
        self.normal_radius = normal_radius
        self.bounds = {}
        for y, row in enumerate(owners):
            for x, building in enumerate(row):
                if building is None:
                    continue
                if building not in self.bounds:
                    self.bounds[building] = [x, y, x, y]
                box = self.bounds[building]
                box[0], box[1] = min(box[0], x), min(box[1], y)
                box[2], box[3] = max(box[2], x), max(box[3], y)
        self.cells = {name: set() for name in self.bounds}
        for y, row in enumerate(owners):
            for x, name in enumerate(row):
                if name:
                    self.cells[name].add((x, y))
        self.levels = {name: "low" for name in self.bounds}
        self.priority = EvacuationPriority()

    def update(self, burning):
        fires = set(burning)
        for name, (x0, y0, x1, y1) in self.bounds.items():
            lab = self.properties[name]["laboratory"] and self.properties[name]["flammable_materials"]
            radius = (self.laboratory_radius if lab else self.normal_radius) * self.scale
            # Caja solo como descarte rapido; la distancia final usa celdas reales.
            nearby = [(x, y) for x, y in fires if x0-radius <= x <= x1+radius and y0-radius <= y <= y1+radius]
            near = any(abs(x-bx)+abs(y-by) <= radius
                       for x, y in nearby for bx, by in self.cells[name])
            self.levels[name] = ("critical" if lab else "high") if near else "low"
        return dict(self.levels)

    def scores(self, origin):
        return {pid: self.priority.calculate_priority(pid, risk_level=self.levels[building])
                for pid, building in origin.items()}

    def update_from_distance(self, distances):
        """Misma distancia Manhattan, consultada una vez desde el campo compartido."""
        if not hasattr(self, "_indices"):
            self._indices = {name: tuple(zip(*sorted(cells))) for name, cells in self.cells.items()}
        for name, (xs, ys) in self._indices.items():
            props = self.properties[name]
            lab = props["laboratory"] and props["flammable_materials"]
            radius = (self.laboratory_radius if lab else self.normal_radius)*self.scale
            self.levels[name] = ("critical" if lab else "high") if distances[ys, xs].min() <= radius else "low"
        return dict(self.levels)
