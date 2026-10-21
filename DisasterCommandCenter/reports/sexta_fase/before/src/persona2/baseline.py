"""P2.4: Decision Tree de referencia, evaluado por sensores reservados."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score, confusion_matrix, f1_score, precision_score, recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, export_text

from .dataset import FEATURE_COLUMNS, SensorDataset, load_sensor_dataset
from .ingestion import DEFAULT_SENSORS_PATH

RANDOM_STATE = 2026
TEST_SIZE = 0.25
MODEL_PARAMETERS = {"max_depth": 3, "min_samples_leaf": 2, "class_weight": "balanced"}
DEPENDENCIES = (
    "scikit-learn", "numpy", "scipy", "joblib", "threadpoolctl", "narwhals", "cloudpickle",
)


@dataclass(frozen=True)
class SensorSplit:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_sensors: tuple[str, ...]
    test_sensors: tuple[str, ...]


def split_by_sensor(
    dataset: SensorDataset, *, test_size: float = TEST_SIZE, random_state: int = RANDOM_STATE
) -> SensorSplit:
    """Reserva sensores completos; estratifica por presencia de algun positivo.

    La etiqueta agregada se usa solo para estratificar grupos, nunca como
    feature. No cambia la particion basandose en metricas del modelo.
    """
    if type(test_size) not in (float, int) or not 0 < test_size < 1:
        raise ValueError("test_size debe ser una fraccion entre 0 y 1.")
    if type(random_state) is not int:
        raise ValueError("random_state debe ser un entero.")
    if (not dataset.X or len(dataset.X) != len(dataset.y)
            or len(dataset.X) != len(dataset.metadata_rows)):
        raise ValueError("X, y y metadatos deben estar alineados y no vacios.")
    if dataset.target_column in dataset.feature_columns or dataset.feature_columns != FEATURE_COLUMNS:
        raise ValueError("X debe contener solo las features de P2.2, sin target.")
    if set(dataset.y) != {False, True}:
        raise ValueError("Se requieren ambas clases para evaluar el baseline.")
    sensor_index = dataset.metadata_columns.index("sensor_id")
    sensors = tuple(row[sensor_index] for row in dataset.metadata_rows)
    group_labels = {}
    for sensor, label in zip(sensors, dataset.y):
        group_labels[sensor] = group_labels.get(sensor, False) or label
    groups = sorted(group_labels)
    strata = [group_labels[sensor] for sensor in groups]
    if set(strata) != {False, True} or min(Counter(strata).values()) < 2:
        raise ValueError(
            "Se requieren al menos dos sensores con positivos y dos sin positivos "
            "para estratificar grupos. No se mezclaran filas como alternativa."
        )
    try:
        train, test = train_test_split(
            groups, test_size=test_size, random_state=random_state, stratify=strata,
        )
    except ValueError as error:
        raise ValueError(f"No se puede reservar grupos con esta fraccion: {error}") from error
    train_set, test_set = set(train), set(test)
    return SensorSplit(
        train_indices=tuple(i for i, sensor in enumerate(sensors) if sensor in train_set),
        test_indices=tuple(i for i, sensor in enumerate(sensors) if sensor in test_set),
        train_sensors=tuple(sorted(train)),
        test_sensors=tuple(sorted(test)),
    )


def binary_metrics(y_true, y_pred) -> dict:
    """Metricas de la clase positiva True; matriz [[TN, FP], [FN, TP]].

    Usa 0 en divisiones indefinidas y enumera cuales no pudieron definirse.
    """
    actual, predicted = tuple(y_true), tuple(y_pred)
    if (not actual or len(actual) != len(predicted)
            or any(type(v) is not bool for v in actual + predicted)):
        raise ValueError("Las etiquetas deben ser bool, no vacias y de igual longitud.")
    matrix = confusion_matrix(actual, predicted, labels=[False, True]).tolist()
    tn, fp = matrix[0]
    fn, tp = matrix[1]
    undefined = []
    if tp + fp == 0:
        undefined.append("precision")
    if tp + fn == 0:
        undefined.append("recall")
    if 2 * tp + fp + fn == 0:
        undefined.append("f1")
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "precision": float(precision_score(actual, predicted, pos_label=True, zero_division=0)),
        "recall": float(recall_score(actual, predicted, pos_label=True, zero_division=0)),
        "f1": float(f1_score(actual, predicted, pos_label=True, zero_division=0)),
        "confusion_matrix": matrix,
        "confusion_matrix_labels": [False, True],
        "undefined_metrics": undefined,
    }


def _class_counts(labels) -> dict:
    counts = Counter(labels)
    total = sum(counts.values())
    return {
        "false": counts[False], "true": counts[True],
        "majority_fraction": max(counts.values()) / total,
        "imbalanced_at_80_percent": max(counts.values()) / total >= .8,
    }


def evaluate_baseline(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH,
    test_size: float = TEST_SIZE, random_state: int = RANDOM_STATE,
) -> dict:
    """Entrena solo en sensores de train y mide una vez en sensores de test.

    Los hiperparametros estan fijados; no busca modelos ni reajusta usando test.
    No guarda un modelo ni lo integra con el simulador.
    """
    dataset = load_sensor_dataset(folder, sensors_path=sensors_path)
    split = split_by_sensor(dataset, test_size=test_size, random_state=random_state)
    X_train = tuple(dataset.X[i] for i in split.train_indices)
    X_test = tuple(dataset.X[i] for i in split.test_indices)
    y_train = tuple(dataset.y[i] for i in split.train_indices)
    y_test = tuple(dataset.y[i] for i in split.test_indices)
    model = DecisionTreeClassifier(**MODEL_PARAMETERS, random_state=random_state)
    model.fit(X_train, y_train)
    predicted = tuple(bool(v) for v in model.predict(X_test))
    reference = DummyClassifier(strategy="most_frequent")
    reference.fit(X_train, y_train)
    reference_predicted = tuple(bool(v) for v in reference.predict(X_test))

    def context(i):
        return dict(zip(dataset.metadata_columns, dataset.metadata_rows[i]))

    train_turns = sorted({context(i)["turn"] for i in split.train_indices})
    test_turns = sorted({context(i)["turn"] for i in split.test_indices})
    return {
        "source": {
            "dataset_kind": dataset.manifest["dataset_kind"],
            "schema_version": dataset.manifest["schema_version"],
            "run_id": dataset.manifest["run_id"],
            "time_unit": dataset.manifest["time_unit"],
            "package_sha256": {
                name: hashlib.sha256((Path(folder) / name).read_bytes()).hexdigest()
                for name in (
                    "lecturas_sensores.csv", "lecturas_sensores.jsonl",
                    "manifiesto_sensores.json",
                )
            },
        },
        "environment": {
            "python": sys.version.split()[0],
            "dependencies": {name: version(name) for name in DEPENDENCIES},
        },
        "feature_columns": list(dataset.feature_columns),
        "target_column": dataset.target_column,
        "split": {
            "strategy": "sensor_holdout_stratified_by_any_positive",
            "random_state": random_state, "test_fraction_of_sensors": test_size,
            "train_sensors": list(split.train_sensors), "test_sensors": list(split.test_sensors),
            "train_records": len(X_train), "test_records": len(X_test),
            "train_turns": train_turns, "test_turns": test_turns,
            "turns_shared_between_sets": sorted(set(train_turns) & set(test_turns)),
            "class_distribution": {
                "train": _class_counts(y_train), "test": _class_counts(y_test),
            },
        },
        "model": {
            "name": "DecisionTreeClassifier",
            "parameters": {**MODEL_PARAMETERS, "random_state": random_state},
            "depth": int(model.get_depth()), "leaves": int(model.get_n_leaves()),
            "feature_importances": {
                name: float(value)
                for name, value in zip(dataset.feature_columns, model.feature_importances_)
            },
            "rules": export_text(model, feature_names=list(dataset.feature_columns)),
        },
        "metrics": binary_metrics(y_test, predicted),
        "majority_reference": {
            "strategy": "most_frequent_from_training_only",
            "predicted_class": reference_predicted[0],
            "metrics": binary_metrics(y_test, reference_predicted),
        },
        "test_predictions": [
            {
                "run_id": context(i)["run_id"], "turn": context(i)["turn"],
                "sensor_id": context(i)["sensor_id"],
                "actual": label, "predicted": prediction,
            }
            for i, label, prediction in zip(split.test_indices, y_test, predicted)
        ],
        "notes": [
            "Datos sinteticos de una sola ejecucion; no son sensores fisicos reales.",
            "Ningun sensor ni lectura se comparte entre entrenamiento y prueba.",
            "Los turnos y el entorno se comparten; no es una evaluacion de futuro temporal.",
            "La estratificacion usa presencia de positivos por sensor solo para particionar.",
            "Los parametros se fijaron antes de medir; no hubo seleccion ni ajuste sobre test.",
            "No se ha medido generalizacion a otras ejecuciones, incendios o datos reales.",
            "La temperatura y el target dependen de proximidad al fuego en el generador.",
            "Un resultado alto puede reflejar esa regla sintetica; no demuestra seguridad operativa.",
            "La referencia mayoritaria muestra por que accuracy sola no basta.",
            "Precision, recall y F1 usan True como clase positiva; divisiones indefinidas valen 0.",
        ],
    }


def render_report(report: dict) -> str:
    split = report["split"]
    lines = [
        "# Persona 2 — P2.4: baseline Decision Tree", "",
        f"Fuente: {report['source']['dataset_kind']}; run_id: {report['source']['run_id']}.",
        "",
        "## Particion por sensores", "",
        f"- Semilla: {split['random_state']}.",
        f"- Entrenamiento: {split['train_records']} lecturas; sensores: "
        + ", ".join(split["train_sensors"]) + ".",
        f"- Prueba: {split['test_records']} lecturas; sensores: "
        + ", ".join(split["test_sensors"]) + ".",
        "- Sensores disjuntos, estratificados por presencia de algun positivo.",
        "- Los mismos turnos se observan en ambos conjuntos; el entorno es compartido.",
        "",
        "| Conjunto | Target false | Target true | Fraccion mayoritaria |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, counts in split["class_distribution"].items():
        lines.append(
            f"| {name} | {counts['false']} | {counts['true']} | "
            f"{counts['majority_fraction']:.6f} |"
        )
    lines += [
        "", "## Metricas en sensores reservados", "",
        "| Referencia | Accuracy | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in (
        ("Decision Tree", report["metrics"]),
        ("Clase mayoritaria de train", report["majority_reference"]["metrics"]),
    ):
        values = " | ".join(f"{metrics[k]:.6f}" for k in ("accuracy", "precision", "recall", "f1"))
        lines.append(f"| {name} | {values} |")
    lines += [
        "", "Clase positiva: True. Matrices: filas reales, columnas predichas; orden False, True.",
    ]
    for name, metrics in (
        ("Decision Tree", report["metrics"]),
        ("Clase mayoritaria", report["majority_reference"]["metrics"]),
    ):
        lines += [
            "", f"### {name}", "",
            "| Real / Predicho | False | True |", "| --- | ---: | ---: |",
            f"| False | {metrics['confusion_matrix'][0][0]} | {metrics['confusion_matrix'][0][1]} |",
            f"| True | {metrics['confusion_matrix'][1][0]} | {metrics['confusion_matrix'][1][1]} |",
            "",
            f"Metricas indefinidas (mostradas como 0): {metrics['undefined_metrics']}.",
        ]
    lines += [
        "", "## Parametros y reglas aprendidas solo en train", "",
        json.dumps(report["model"]["parameters"], ensure_ascii=False, sort_keys=True),
        "",
        "Features: " + ", ".join(report["feature_columns"]) + ".",
        "", "~~~text", report["model"]["rules"].rstrip(), "~~~",
        "", "## Alcance", "",
    ]
    lines.extend(f"- {note}" for note in report["notes"])
    lines += [
        "", "## Reproducibilidad", "",
        f"Python: {report['environment']['python']}.",
    ]
    lines.extend(
        f"- {name}=={value}" for name, value in report["environment"]["dependencies"].items()
    )
    lines += ["", "SHA-256 del paquete:", ""]
    lines.extend(
        f"- {name}: {value}" for name, value in report["source"]["package_sha256"].items()
    )
    lines += ["", "El JSON incluye las predicciones de test y sus claves para auditoria.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="P2.4: baseline sintetico con sensores reservados")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--sensors-path", type=Path, default=DEFAULT_SENSORS_PATH)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_baseline(args.folder, sensors_path=args.sensors_path)
    except ValueError as error:
        parser.error(str(error))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "informe_baseline.json").write_text(serialized, encoding="utf-8")
        (args.output_dir / "informe_baseline.md").write_text(render_report(report), encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
