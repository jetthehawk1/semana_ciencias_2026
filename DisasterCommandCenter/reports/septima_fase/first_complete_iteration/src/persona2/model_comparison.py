"""P2.5: comparacion descriptiva con el protocolo fijo de P2.4."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import warnings

from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import RANDOM_STATE, TEST_SIZE, binary_metrics, evaluate_baseline
from .dataset import load_sensor_dataset
from .ingestion import DEFAULT_SENSORS_PATH

LOGISTIC_PARAMETERS = {
    "solver": "lbfgs", "C": 1.0, "class_weight": "balanced",
    "max_iter": 2000, "tol": 1e-4,
}
FOREST_PARAMETERS = {
    "n_estimators": 100, "max_depth": 3, "min_samples_leaf": 2,
    "max_features": "sqrt", "bootstrap": True, "class_weight": "balanced", "n_jobs": 1,
}


def _additional_models(random_state):
    return {
        "logistic_regression": Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(**LOGISTIC_PARAMETERS, random_state=random_state)),
        ]),
        "random_forest": RandomForestClassifier(**FOREST_PARAMETERS, random_state=random_state),
    }


def compare_models(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH,
    test_size: float = TEST_SIZE, random_state: int = RANDOM_STATE,
) -> dict:
    """Reutiliza el baseline, sus grupos y metricas; agrega LR y RF sin tuning.

    El holdout ya fue inspeccionado en P2.4. No selecciona un modelo ganador
    ni lo reajusta con test. Estandariza solo LR, dentro de su pipeline.
    """
    baseline = evaluate_baseline(
        folder, sensors_path=sensors_path, test_size=test_size, random_state=random_state
    )
    dataset = load_sensor_dataset(folder, sensors_path=sensors_path)
    if any(
        hashlib.sha256((Path(folder) / name).read_bytes()).hexdigest() != digest
        for name, digest in baseline["source"]["package_sha256"].items()
    ):
        raise ValueError("El paquete cambio durante la comparacion.")
    sensor_index = dataset.metadata_columns.index("sensor_id")
    train_sensors = set(baseline["split"]["train_sensors"])
    test_sensors = set(baseline["split"]["test_sensors"])
    train_indices = tuple(
        i for i, row in enumerate(dataset.metadata_rows) if row[sensor_index] in train_sensors
    )
    test_indices = tuple(
        i for i, row in enumerate(dataset.metadata_rows) if row[sensor_index] in test_sensors
    )
    X_train = tuple(dataset.X[i] for i in train_indices)
    X_test = tuple(dataset.X[i] for i in test_indices)
    y_train = tuple(dataset.y[i] for i in train_indices)
    y_test = tuple(dataset.y[i] for i in test_indices)
    results = {
        "decision_tree": {
            "name": baseline["model"]["name"],
            "parameters": baseline["model"]["parameters"],
            "preprocessing": "none",
            "metrics": baseline["metrics"],
            "test_predictions": baseline["test_predictions"],
            "fit_warnings": [],
            "diagnostics": {
                key: baseline["model"][key]
                for key in ("depth", "leaves", "feature_importances", "rules")
            },
        },
    }
    for key, estimator in _additional_models(random_state).items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            estimator.fit(X_train, y_train)
        predicted = tuple(bool(value) for value in estimator.predict(X_test))
        parameters = (
            LOGISTIC_PARAMETERS if key == "logistic_regression" else FOREST_PARAMETERS
        )
        results[key] = {
            "name": "LogisticRegression" if key == "logistic_regression" else "RandomForestClassifier",
            "parameters": {**parameters, "random_state": random_state},
            "preprocessing": "StandardScaler fitted on train" if key == "logistic_regression" else "none",
            "metrics": binary_metrics(y_test, predicted),
            "test_predictions": [
                {**original, "predicted": value}
                for original, value in zip(baseline["test_predictions"], predicted)
            ],
            "fit_warnings": [
                {"category": warning.category.__name__, "message": str(warning.message)}
                for warning in caught
            ],
        }
        if key == "logistic_regression":
            scaler = estimator.named_steps["scaler"]
            classifier = estimator.named_steps["classifier"]
            results[key]["diagnostics"] = {
                "converged": not any(
                    issubclass(warning.category, ConvergenceWarning) for warning in caught
                ),
                "iterations": classifier.n_iter_.tolist(),
                "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(),
            }
        else:
            results[key]["diagnostics"] = {
                "fitted_tree_count": len(estimator.estimators_),
                "feature_importances": {
                    name: float(value)
                    for name, value in zip(dataset.feature_columns, estimator.feature_importances_)
                },
            }
    return {
        "source": baseline["source"],
        "environment": baseline["environment"],
        "feature_columns": baseline["feature_columns"],
        "target_column": baseline["target_column"],
        "split": baseline["split"],
        "models": {
            key: results[key] for key in
            ("logistic_regression", "decision_tree", "random_forest")
        },
        "majority_reference": baseline["majority_reference"],
        "selection": {
            "selected_model": None,
            "reason": (
                "Comparacion descriptiva sobre el holdout ya observado en P2.4; "
                "no hay validacion independiente para elegir un modelo definitivo."
            ),
        },
        "notes": baseline["notes"] + [
            "Los tres modelos usan la misma particion y las mismas features.",
            "LR estandariza solo con train; arbol y bosque reciben las features sin escalar.",
            "RF usa 100 arboles con n_jobs=1; no hay busqueda de hiperparametros.",
            "Se reutiliza el holdout de P2.4; las metricas no son una prueba final independiente.",
            "No se selecciona automaticamente un ganador ni se reentrena con el conjunto completo.",
        ],
    }


def render_report(report: dict) -> str:
    split = report["split"]
    lines = [
        "# Persona 2 — P2.5: comparacion de modelos", "",
        f"Fuente: {report['source']['dataset_kind']}; run_id: {report['source']['run_id']}.",
        "",
        f"Entrenamiento: {split['train_records']} lecturas de {len(split['train_sensors'])} sensores.",
        f"Prueba: {split['test_records']} lecturas de {len(split['test_sensors'])} sensores.",
        "Sensores de test: " + ", ".join(split["test_sensors"]) + ".",
        f"Semilla: {split['random_state']}. Particion: {split['strategy']}.",
        "Features: " + ", ".join(report["feature_columns"]) + ".",
        "",
        "| Conjunto | Target false | Target true | Fraccion mayoritaria |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, counts in split["class_distribution"].items():
        lines.append(
            f"| {key} | {counts['false']} | {counts['true']} | "
            f"{counts['majority_fraction']:.6f} |"
        )
    lines += [
        "", "## Resultados medidos", "",
        "| Modelo | Accuracy | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    entries = [
        (model["name"], model["metrics"]) for model in report["models"].values()
    ] + [("Clase mayoritaria de train", report["majority_reference"]["metrics"])]
    for name, metrics in entries:
        values = " | ".join(f"{metrics[key]:.6f}" for key in ("accuracy", "precision", "recall", "f1"))
        lines.append(f"| {name} | {values} |")
    lines += [
        "",
        "Matrices: filas reales, columnas predichas; orden False, True. Clase positiva: True.",
    ]
    for name, metrics in entries:
        matrix = metrics["confusion_matrix"]
        lines += [
            "", f"### {name}", "",
            "| Real / Predicho | False | True |", "| --- | ---: | ---: |",
            f"| False | {matrix[0][0]} | {matrix[0][1]} |",
            f"| True | {matrix[1][0]} | {matrix[1][1]} |",
            "", f"Metricas indefinidas (mostradas como 0): {metrics['undefined_metrics']}.",
        ]
    lines += ["", "## Parametros fijados antes de medir", ""]
    for model in report["models"].values():
        lines += [
            f"### {model['name']}", "",
            f"Preprocesamiento: {model['preprocessing']}.", "",
            "~~~json",
            json.dumps(model["parameters"], indent=2, ensure_ascii=False, sort_keys=True),
            "~~~", "",
            f"Avisos de entrenamiento: {json.dumps(model['fit_warnings'], ensure_ascii=False)}.",
            "",
        ]
        if "converged" in model["diagnostics"]:
            lines.append(f"Convergencia de LR: {model['diagnostics']['converged']}.")
            lines.append("")
    lines += ["## Interpretacion", "", report["selection"]["reason"], ""]
    lines.extend(f"- {note}" for note in report["notes"])
    lines += ["", "## Reproducibilidad", "", f"Python: {report['environment']['python']}."]
    lines.extend(f"- {name}=={value}" for name, value in report["environment"]["dependencies"].items())
    lines += ["", "SHA-256 del paquete:", ""]
    lines.extend(f"- {name}: {value}" for name, value in report["source"]["package_sha256"].items())
    lines += ["", "El JSON conserva predicciones identificadas de test para cada modelo.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="P2.5: comparacion descriptiva LR/DT/RF")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--sensors-path", type=Path, default=DEFAULT_SENSORS_PATH)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        report = compare_models(args.folder, sensors_path=args.sensors_path)
    except ValueError as error:
        parser.error(str(error))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "informe_comparacion.json").write_text(serialized, encoding="utf-8")
        (args.output_dir / "informe_comparacion.md").write_text(render_report(report), encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
