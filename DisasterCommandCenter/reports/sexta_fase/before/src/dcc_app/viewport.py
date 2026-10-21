"""Camara del mapa: zoom, desplazamiento y encuadre; independiente de pygame."""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass
class Viewport:
    map_width: int
    map_height: int
    zoom: float = 4.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    def fit(self, rect: tuple[int, int, int, int]) -> None:
        x, y, w, h = rect
        self.zoom = max(0.2, min((w-28) / self.map_width, (h-28) / self.map_height))
        self.offset_x = x + (w-self.map_width*self.zoom)/2
        self.offset_y = y + (h-self.map_height*self.zoom)/2

    def zoom_at(self, px: float, py: float, wheel: int) -> None:
        old_zoom = self.zoom
        self.zoom = max(0.5, min(50.0, self.zoom * (1.16 ** wheel)))
        self.offset_x = px - (px-self.offset_x) * (self.zoom/old_zoom)
        self.offset_y = py - (py-self.offset_y) * (self.zoom/old_zoom)

    def pan(self, dx: int, dy: int) -> None:
        self.offset_x += dx
        self.offset_y += dy

    def project(self, x: float, y: float) -> tuple[int, int]:
        return round(self.offset_x+x*self.zoom), round(self.offset_y+y*self.zoom)

    def cell_at(self, px: float, py: float, *, clip_rect=None):
        """Inversa para seleccion: recorta paneles y margenes fuera del campus."""
        if clip_rect is not None:
            x, y, width, height = clip_rect
            if not (x <= px < x+width and y <= py < y+height):
                return None
        gx = math.floor((px-self.offset_x)/self.zoom)
        gy = math.floor((py-self.offset_y)/self.zoom)
        return (gx, gy) if 0 <= gx < self.map_width and 0 <= gy < self.map_height else None
