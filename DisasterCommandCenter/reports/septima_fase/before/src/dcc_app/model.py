"""Modelo de solo lectura para la interfaz del Paso 14.4.1.

NO importa ni modifica los modulos de simulation.
La cuadricula se reconstruye en el mismo orden de zonas del campus.json.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path

TRANSITABLE = frozenset({'floor', 'road'})
TERRAINS = frozenset({'grass', 'floor', 'road', 'building'})


@dataclass(frozen=True)
class CampusSnapshot:
    name: str
    width: int
    height: int
    terrain: tuple[tuple[str, ...], ...]
    owners: tuple[tuple[str | None, ...], ...]
    centers: dict[str, tuple[float, float]]
    entrances: tuple[tuple[str, int, int], ...]
    terrain_count: dict[str, int]

    @property
    def building_count(self) -> int:
        return len(self.centers)

    def terrain_at(self, x: int, y: int) -> str:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError('Celda fuera del mapa')
        return self.terrain[y][x]


def load_campus(campus_file: str | Path, entrances_file: str | Path) -> CampusSnapshot:
    """Lee y valida JSON; nunca guarda archivos ni cambia la simulacion."""
    campus_file, entrances_file = Path(campus_file), Path(entrances_file)
    campus = json.loads(campus_file.read_text(encoding='utf-8'))
    entrances = json.loads(entrances_file.read_text(encoding='utf-8'))

    w, h = campus['width'], campus['height']
    if type(w) is not int or type(h) is not int or w <= 0 or h <= 0:
        raise ValueError('Dimensiones del campus invalidas')
    default = campus['default_terrain']
    if default not in TERRAINS:
        raise ValueError('Terreno predeterminado invalido')
    if not isinstance(campus.get('zones'), list):
        raise ValueError('El campus no contiene zonas validas')

    grid = [[default] * w for _ in range(h)]
    owner = [[None] * w for _ in range(h)]
    for idx, zone in enumerate(campus['zones']):
        x, y, zw, zh = (zone[field] for field in ('x', 'y', 'width', 'height'))
        name, kind = zone['name'], zone['terrain_type']
        if kind not in TERRAINS:
            raise ValueError(f'Terreno desconocido en zona {idx}: {kind}')
        if any(type(v) is not int for v in (x, y, zw, zh)):
            raise ValueError(f'Coordenadas no enteras en zona {idx}')
        if x < 0 or y < 0 or zw <= 0 or zh <= 0 or x + zw > w or y + zh > h:
            raise ValueError(f'Zona {idx} fuera de limites: {name}')
        for yy in range(y, y + zh):
            for xx in range(x, x + zw):
                grid[yy][xx] = kind
                owner[yy][xx] = name if kind == 'building' else None

    stats = defaultdict(lambda: [0., 0., 0])
    for yy in range(h):
        for xx in range(w):
            label = owner[yy][xx]
            if label is not None:
                s = stats[label]
                s[0] += xx + 0.5
                s[1] += yy + 0.5
                s[2] += 1
    centers = {k: (s[0] / s[2], s[1] / s[2]) for k, s in stats.items()}

    if entrances.get('width') != w or entrances.get('height') != h:
        raise ValueError('Las dimensiones de los accesos no coinciden con el campus')
    access_list = []
    for idx, access in enumerate(entrances['accesses']):
        building = access['building']
        ix, iy = access['interior_cell']['x'], access['interior_cell']['y']
        ex, ey = access['exterior_cell']['x'], access['exterior_cell']['y']
        if not all(type(v) is int for v in (ix, iy, ex, ey)):
            raise ValueError(f'Acceso {idx}: coordenadas invalidas')
        if not (0 <= ix < w and 0 <= iy < h and 0 <= ex < w and 0 <= ey < h):
            raise ValueError(f'Acceso {idx}: fuera del mapa')
        if owner[iy][ix] != building:
            raise ValueError(f'Acceso {idx}: celda interior no pertenece a {building}')
        if grid[ey][ex] not in TRANSITABLE or abs(ix-ex) + abs(iy-ey) != 1:
            raise ValueError(f'Acceso {idx}: salida exterior invalida')
        access_list.append((building, ex, ey))

    return CampusSnapshot(
        name=str(campus.get('name', 'Campus')),
        width=w, height=h,
        terrain=tuple(tuple(r) for r in grid),
        owners=tuple(tuple(r) for r in owner),
        centers=centers,
        entrances=tuple(access_list),
        terrain_count=dict(Counter(t for row in grid for t in row)),
    )
