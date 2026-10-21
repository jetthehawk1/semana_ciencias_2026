"""P2.3: analisis descriptivo de paquetes sinteticos validados, sin entrenar."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean, median, pstdev

from .dataset import load_sensor_dataset
from .ingestion import DEFAULT_SENSORS_PATH

IMBALANCE_THRESHOLD = 0.80


def _distribution(values) -> dict:
    counts = Counter(values)
    total = sum(counts.values())
    return {
        "counts": {"false": counts[False], "true": counts[True]},
        "proportions": {
            "false": counts[False] / total, "true": counts[True] / total
        },
    }


def analyze_sensor_package(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH
) -> dict:
    """Calcula un informe JSON-serializable sobre la representacion de P2.2.

    Los tipos descritos son posteriores a P2.2: mediciones float, alarm int
    0/1 y target bool. No imputa nulos ni acepta paquetes invalidos.
    """
    dataset = load_sensor_dataset(folder, sensors_path=sensors_path)
    columns = {}
    for name, values in zip(dataset.feature_columns, zip(*dataset.X)):
        columns[name] = ("feature", values)
    for name, values in zip(dataset.metadata_columns, zip(*dataset.metadata_rows)):
        columns[name] = ("metadata", values)
    columns[dataset.target_column] = ("target", dataset.y)

    profiles = {}
    for name, (role, values) in columns.items():
        nulls = sum(value is None for value in values)
        profiles[name] = {
            "role": role,
            "types": dict(sorted(Counter(type(value).__name__ for value in values).items())),
            "null_count": nulls,
            "allowed_null_count": nulls if name == "building_id" else 0,
            "missing_required_count": nulls if name != "building_id" else 0,
            "unique_non_null": len({value for value in values if value is not None}),
        }

    sensors = columns["sensor_id"][1]
    turns = columns["turn"][1]
    statistics = {}
    for name in ("temperature_c", "smoke_index"):
        values = columns[name][1]
        statistics[name] = {
            "count": len(values), "min": min(values), "max": max(values),
            "mean": mean(values), "median": median(values),
            "stddev_population": pstdev(values),
        }

    target = _distribution(dataset.y)
    majority = max(target["proportions"].values())
    target.update(
        name=dataset.target_column,
        single_class=any(count == 0 for count in target["counts"].values()),
        majority_fraction=majority,
        imbalance_threshold=IMBALANCE_THRESHOLD,
        imbalanced=majority >= IMBALANCE_THRESHOLD,
    )
    by_sensor = {}
    for sensor in sorted(set(sensors)):
        indices = [i for i, sid in enumerate(sensors) if sid == sensor]
        by_sensor[sensor] = {
            "records": len(indices),
            "target_counts": _distribution(dataset.y[i] for i in indices)["counts"],
        }

    return {
        "source": {
            "schema_version": dataset.manifest["schema_version"],
            "dataset_kind": dataset.manifest["dataset_kind"],
            "time_unit": dataset.manifest["time_unit"],
            "run_id": dataset.manifest["run_id"],
            "package_sha256": {
                name: hashlib.sha256((Path(folder) / name).read_bytes()).hexdigest()
                for name in (
                    "lecturas_sensores.csv", "lecturas_sensores.jsonl",
                    "manifiesto_sensores.json",
                )
            },
        },
        "summary": {
            "records": len(dataset.X), "sensor_count": len(set(sensors)),
            "turn_count": len(set(turns)), "first_turn": min(turns),
            "last_turn": max(turns), "feature_count": len(dataset.feature_columns),
            "missing_required_values": sum(
                profile["missing_required_count"] for profile in profiles.values()
            ),
            "allowed_null_values": sum(
                profile["allowed_null_count"] for profile in profiles.values()
            ),
        },
        "feature_columns": list(dataset.feature_columns),
        "columns": profiles,
        "numeric_statistics": statistics,
        "alarm_distribution": _distribution(columns["alarm"][1]),
        "target": target,
        "by_sensor": by_sensor,
        "records_by_turn": {
            str(turn): count for turn, count in sorted(Counter(turns).items())
        },
        "notes": [
            "Datos sinteticos: no representan sensores fisicos reales.",
            "Los turnos son pasos de simulacion, no segundos ni fechas.",
            "El analisis solo recibe paquetes que superan P2.1; un paquete invalido se rechaza.",
            "building_id=None es valido para sensores exteriores; no es una medicion perdida.",
            "Los tipos corresponden a P2.2: mediciones float, alarm int 0/1, target bool.",
            "fire_within_2_cells se analiza como target y permanece fuera de X.",
            "Desbalance: regla descriptiva de clase mayoritaria >=80%, no criterio universal.",
            "Las lecturas de un mismo sensor y turnos cercanos no son muestras independientes.",
        ],
    }


def render_report(report: dict) -> str:
    """Presenta los mismos resultados del JSON en un informe Markdown."""
    summary, target = report["summary"], report["target"]
    lines = [
        "# Persona 2 — P2.3: analisis exploratorio",
        "",
        f"Fuente: {report['source']['dataset_kind']}; ejecucion: {report['source']['run_id']}.",
        "",
        "| Medida | Valor |", "| --- | ---: |",
    ]
    for name, value in summary.items():
        lines.append(f"| {name} | {value} |")
    lines += [
        "", "## Columnas de P2.2", "",
        "| Columna | Rol | Tipos observados (conteos) | Nulos permitidos | Ausentes obligatorios |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for name, profile in report["columns"].items():
        types = ", ".join(f"{kind}: {count}" for kind, count in profile["types"].items())
        lines.append(
            f"| {name} | {profile['role']} | {types} | "
            f"{profile['allowed_null_count']} | {profile['missing_required_count']} |"
        )
    lines += [
        "", "## Target: fire_within_2_cells", "",
        "| Clase | Lecturas | Porcentaje |", "| --- | ---: | ---: |",
    ]
    for label in ("false", "true"):
        lines.append(
            f"| {label} | {target['counts'][label]} | "
            f"{100 * target['proportions'][label]:.2f}% |"
        )
    lines += [
        "",
        f"Clase unica: {target['single_class']}. "
        f"Desbalance segun umbral del 80%: {target['imbalanced']}.",
        "",
        "## Temperatura y humo", "",
        "Desviacion estandar poblacional (ddof=0); sin redondeo adicional en JSON.",
        "",
        "| Variable | n | Min | Max | Media | Mediana | Desv. poblacional |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in report["numeric_statistics"].items():
        values = " | ".join(
            f"{stats[key]:.6f}" for key in ("min", "max", "mean", "median", "stddev_population")
        )
        lines.append(f"| {name} | {stats['count']} | {values} |")
    alarm = report["alarm_distribution"]
    lines += [
        "",
        f"Alarma: {alarm['counts']['true']} activas "
        f"({100 * alarm['proportions']['true']:.2f}%) y "
        f"{alarm['counts']['false']} inactivas.",
        "",
        "## Cobertura por sensor", "",
        "| Sensor | Lecturas | Target false | Target true |",
        "| --- | ---: | ---: | ---: |",
    ]
    for sensor, data in report["by_sensor"].items():
        lines.append(
            f"| {sensor} | {data['records']} | "
            f"{data['target_counts']['false']} | {data['target_counts']['true']} |"
        )
    lines += ["", "## Cobertura por turno", "", "| Turno | Lecturas |", "| --- | ---: |"]
    lines.extend(f"| {turn} | {count} |" for turn, count in report["records_by_turn"].items())
    lines += ["", "## Alcance e interpretacion", ""]
    lines.extend(f"- {note}" for note in report["notes"])
    lines += ["", "## SHA-256 del paquete analizado", ""]
    lines.extend(
        f"- {name}: {digest}" for name, digest in report["source"]["package_sha256"].items()
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="P2.3: EDA de sensores sinteticos validados")
    parser.add_argument("folder", type=Path, help="Paquete CSV/JSONL/manifiesto de Persona 1")
    parser.add_argument("--sensors-path", type=Path, default=DEFAULT_SENSORS_PATH)
    parser.add_argument("--output-dir", type=Path, help="Guardar informe_eda.json y .md")
    args = parser.parse_args()
    try:
        report = analyze_sensor_package(args.folder, sensors_path=args.sensors_path)
    except ValueError as error:
        parser.error(str(error))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "informe_eda.json").write_text(serialized, encoding="utf-8")
        (args.output_dir / "informe_eda.md").write_text(render_report(report), encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
