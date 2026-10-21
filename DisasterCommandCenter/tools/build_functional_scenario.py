"""Deriva un escenario 3x reproducible sin editar el campus/contrato fuente."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from simulation.indoor_people import IndoorPersonManager
from tools.functional_geometry import orient_entrances, vegetation_layout, add_alternative_entrances


def build(root=ROOT):
    root = Path(root)
    data = root / "data"
    config = json.loads((data / "functional_scenario.json").read_text(encoding="utf-8"))
    scale = config["subdivision"]
    if type(scale) is not int or scale < 3 or scale > 4:
        raise ValueError("subdivision debe ser 3 o 4 para capacidad y coste acotados.")
    low, high = config["population_min"], config["population_max"]
    if type(low) is not int or type(high) is not int or not 1 <= low <= high:
        raise ValueError("Rango de poblacion invalido.")
    source = json.loads((data / "campus.json").read_text(encoding="utf-8"))
    manager = IndoorPersonManager(source)
    sizes = Counter(name for row in manager.building_owners for name in row if name)
    if not set(config["laboratory_buildings"]).issubset(sizes):
        raise ValueError("Laboratorio ausente del plano.")
    fine = deepcopy(source)
    fine["name"] += " | escenario detallado"
    fine["width"] *= scale
    fine["height"] *= scale
    fine["source_grid"] = {"width": source["width"], "height": source["height"], "subdivision": scale}
    for zone in fine["zones"]:
        for key in ("x", "y", "width", "height"):
            zone[key] *= scale
    doors = json.loads((data / "building_entrances.json").read_text(encoding="utf-8"))
    doors["accesses"] = orient_entrances(manager, doors["accesses"], config.get("entrance_orientations", {}))
    doors["accesses"], doors["exit_policy"] = add_alternative_entrances(
        manager, doors["accesses"], sizes, config["multiple_exit_policy"])
    sensors = json.loads((data / "sensores_paso_13.json").read_text(encoding="utf-8"))["sensors"]
    vegetation = vegetation_layout(manager, doors["accesses"], config, sensors)
    for x, y in vegetation["cells_source"]:
        fine["zones"].append({"name": f"vegetation-{x}-{y}", "x": x*scale, "y": y*scale,
                              "width": scale, "height": scale, "terrain_type": "grass"})
    doors["width"], doors["height"], doors["map_name"] = fine["width"], fine["height"], fine["name"]
    expanded = []
    for door in doors["accesses"]:
        ix, iy = door["interior_cell"]["x"], door["interior_cell"]["y"]
        ox, oy = door["exterior_cell"]["x"], door["exterior_cell"]["y"]
        dx, dy = ox-ix, oy-iy
        for offset in range(scale):
            item = deepcopy(door)
            item["id"] += f"-sub{offset+1}"
            if dx:
                inside = (ix*scale + (scale-1 if dx > 0 else 0), iy*scale+offset)
                outside = (ox*scale + (0 if dx > 0 else scale-1), oy*scale+offset)
            else:
                inside = (ix*scale+offset, iy*scale + (scale-1 if dy > 0 else 0))
                outside = (ox*scale+offset, oy*scale + (0 if dy > 0 else scale-1))
            item["interior_cell"] = dict(zip(("x", "y"), inside))
            item["exterior_cell"] = dict(zip(("x", "y"), outside))
            item["source_interior_cell"] = {"x": ix, "y": iy}
            item["source_exterior_cell"] = {"x": ox, "y": oy}
            expanded.append(item)
    doors["accesses"] = expanded
    minimum, maximum = min(sizes.values()), max(sizes.values())
    counts = {name: low + math.floor((high-low)*(size-minimum)/max(1,maximum-minimum)+0.5)
              for name, size in sorted(sizes.items())}
    population = {"description": "Poblacion sintetica por area efectiva del plano fuente.",
                  "seed": config["seed"], "id_prefix": "P", "building_counts": counts,
                  "source_cell_areas": dict(sorted(sizes.items())),
                  "formula": "min + floor((max-min)*(area-area_min)/(area_max-area_min)+0.5)"}
    building_properties = {name: {"laboratory": name in config["laboratory_buildings"],
                                "flammable_materials": name in config["laboratory_buildings"]}
                           for name in sorted(sizes)}
    output = data / "functional"
    output.mkdir(exist_ok=True)
    for filename, content in (("campus.json", fine), ("building_entrances.json", doors),
                              ("population.json", population), ("building_properties.json", building_properties),
                              ("vegetation.json", vegetation)):
        (output / filename).write_text(json.dumps(content, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return {"width": fine["width"], "height": fine["height"], "buildings": len(counts),
            "people": sum(counts.values()), "minimum": min(counts.values()),
            "maximum": max(counts.values()), "accesses": len(expanded),
            "vegetation_source_cells": vegetation["converted_source_cells"]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
