"""Geometria determinista de puertas y jardines del escenario, sin Pygame."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
import math

DIRECTIONS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


def area_percentile(areas, fraction):
    values = sorted(areas)
    index = (len(values)-1)*fraction
    lo = math.floor(index)
    return values[lo] + (values[math.ceil(index)]-values[lo])*(index-lo)


def add_alternative_entrances(manager, accesses, sizes, policy):
    """Anade fachadas distintas sin reemplazar ningun acceso existente."""
    if not 0 < policy["large_percentile"] < policy["very_large_percentile"] < 1:
        raise ValueError("Percentiles de salidas invalidos.")
    large = area_percentile(sizes.values(), policy["large_percentile"])
    very_large = area_percentile(sizes.values(), policy["very_large_percentile"])
    result = deepcopy(accesses)
    for item in result:
        inside, outside = item["interior_cell"], item["exterior_cell"]
        vector = (outside["x"]-inside["x"], outside["y"]-inside["y"])
        item["orientation"] = next(side for side, delta in DIRECTIONS.items() if delta == vector)
        item["role"] = "primary"
    report = {"large_area_threshold": large, "very_large_area_threshold": very_large, "buildings": {}}
    for name, area in sorted(sizes.items()):
        wanted = (policy["very_large_min_exits"] if area >= very_large else
                  policy["large_min_exits"] if area >= large else 1)
        if type(wanted) is not int or not 1 <= wanted <= 4:
            raise ValueError("Se permiten entre una y cuatro fachadas por edificio.")
        existing = [a for a in result if a["building"] == name]
        before = len(existing)
        while len(existing) < wanted:
            used = {a["orientation"] for a in existing}
            occupied_inside = {(a["interior_cell"]["x"], a["interior_cell"]["y"]) for a in result}
            occupied_outside = {(a["exterior_cell"]["x"], a["exterior_cell"]["y"]) for a in result}
            candidates = []
            for side in DIRECTIONS.keys()-used:
                try:
                    candidate = orient_entrances(manager, [], {name: [side]})[0]
                except ValueError:
                    continue
                p, q = candidate["interior_cell"], candidate["exterior_cell"]
                if (p["x"], p["y"]) in occupied_inside or (q["x"], q["y"]) in occupied_outside:
                    continue
                separation = min(abs(p["x"]-a["interior_cell"]["x"])+abs(p["y"]-a["interior_cell"]["y"]) for a in existing)
                candidates.append((separation, side, candidate))
            if not candidates:
                break
            _, _, added = max(candidates, key=lambda item: (item[0], item[1]))
            added["id"] = f"secondary-{name}-{added['orientation']}"
            added["role"] = "secondary"
            result.append(added)
            existing.append(added)
        report["buildings"][name] = {"source_area": area, "previous": before, "required": wanted,
                                   "actual": len(existing), "limited_by_geometry": len(existing) < wanted}
    return result, report


def orient_entrances(manager, original, orientations):
    """Elige borde mas extremo y despues punto mas cercano al centro del lado."""
    if not set(orientations).issubset(manager.building_ids):
        raise ValueError("Orientacion para edificio inexistente.")
    accesses = [deepcopy(a) for a in original if a["building"] not in orientations]
    for building, sides in sorted(orientations.items()):
        if not sides or len(set(sides)) != len(sides) or not set(sides).issubset(DIRECTIONS):
            raise ValueError("Orientaciones invalidas o duplicadas.")
        cells = [(x, y) for y, row in enumerate(manager.building_owners)
                 for x, name in enumerate(row) if name == building]
        cx = sum(x for x, y in cells)/len(cells)
        cy = sum(y for x, y in cells)/len(cells)
        for side in sides:
            dx, dy = DIRECTIONS[side]
            candidates = [(x, y) for x, y in cells if manager.is_transitable(x+dx, y+dy)]
            if not candidates:
                raise ValueError(f"{building}: no hay exterior transitable hacia {side}.")
            x, y = min(candidates, key=lambda p: (
                -(p[0]*dx+p[1]*dy), abs(p[0]-cx) if dy else abs(p[1]-cy), p))
            accesses.append({"id": f"functional-{building}-{side}", "building": building,
                "orientation": side, "interior_cell": {"x": x, "y": y},
                "exterior_cell": {"x": x+dx, "y": y+dy}})
    return accesses


def vegetation_layout(manager, accesses, config, sensors):
    """Conserva un arbol peatonal hasta reuniones antes de delimitar jardines.

    Reinterpreta floor mediante parches y una mascara distribuida reproducible.
    road, edificios, reuniones, puertas y sensores quedan excluidos.
    """
    meeting_cells = set()
    for area in config["meeting_areas"]:
        x, y, w, h = area["bounds_source"]
        meeting_cells.update((xx, yy) for yy in range(y, y+h) for xx in range(x, x+w)
                             if manager.is_transitable(xx, yy))
    parents = {min(meeting_cells): None}
    queue = deque(parents)
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRECTIONS.values():
            point = (x+dx, y+dy)
            if point not in parents and manager.is_transitable(*point):
                parents[point] = (x, y)
                queue.append(point)
    reserved = set(meeting_cells)
    # Conectar tambien las reuniones entre si antes de convertir suelo abierto.
    for area in config["meeting_areas"]:
        x, y, w, h = area["bounds_source"]
        point = next(((xx, yy) for yy in range(y, y+h) for xx in range(x, x+w)
                      if (xx, yy) in parents), None)
        if point is None:
            raise ValueError(f"Reunion desconectada: {area['id']}")
        while point is not None:
            reserved.add(point)
            point = parents[point]
    for access in accesses:
        p = access["exterior_cell"]
        point = (p["x"], p["y"])
        if point not in parents:
            raise ValueError(f"Acceso sin conexion a reuniones: {access['id']}")
        while point is not None and point not in reserved:
            reserved.add(point)
            point = parents[point]
    reserved.update((s["x"], s["y"]) for s in sensors if manager.is_transitable(s["x"], s["y"]))
    vegetation = set()
    patches = []
    for patch in config.get("vegetation_patches_source", []):
        x, y, w, h = patch["bounds"]
        if any(type(n) is not int for n in (x, y, w, h)) or min(x, y) < 0 or min(w, h) < 1 or x+w > manager.width or y+h > manager.height:
            raise ValueError("Parche vegetal fuera del plano.")
        cells = {(xx, yy) for yy in range(y, y+h) for xx in range(x, x+w)
                 if manager.terrain[yy][xx] == "floor" and (xx, yy) not in reserved}
        vegetation.update(cells)
        patches.append({"id": patch["id"], "bounds_source": patch["bounds"],
                        "cells_source": [list(p) for p in sorted(cells)]})
    distributed = config.get("vegetation_distribution", {})
    if distributed.get("enabled", False):
        tile = distributed["patch_scale_source_cells"]
        coverage = distributed["eligible_tile_fraction"]
        if type(tile) is not int or tile < 2 or not 0 <= coverage <= 1:
            raise ValueError("Mascara vegetal invalida.")
        tiles = {}
        for y, row in enumerate(manager.terrain):
            for x, kind in enumerate(row):
                if kind != "floor" or (x, y) in reserved:
                    continue
                key = (x//tile, y//tile)
                if key not in tiles:
                    digest = hashlib.sha256(f"{config['seed']}:vegetation:{key[0]}:{key[1]}".encode()).digest()
                    tiles[key] = int.from_bytes(digest[:8], "big") / 2**64 < coverage
                if tiles[key]:
                    vegetation.add((x, y))
    return {"schema_version": "1.0", "subdivision": config["subdivision"],
            "description": "Mascara didactica de suelo natural distribuido; no levantamiento botanico ni georreferenciado.",
            "distribution": distributed,
            "patches": patches, "cells_source": [list(p) for p in sorted(vegetation)],
            "protected_walkways_source": [list(p) for p in sorted(reserved-meeting_cells)],
            "converted_source_cells": len(vegetation)}
