"""Compara Ridge y persistencia en secuencias virtuales independientes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from wind_prediction.dataset import feature_names, split_sequences, temporal_examples
from wind_prediction.model import vector_prediction
from wind_prediction.synthetic import synthetic_sequences


def metrics(targets, predictions):
    squared, speeds, angles = [], [], []
    for (tu, tv), (u, v) in zip(targets, predictions):
        squared.extend(((tu-u)**2, (tv-v)**2))
        ts, ps = math.hypot(tu, tv), math.hypot(u, v)
        speeds.append(abs(ts-ps))
        if min(ts, ps) > 1e-8:
            angles.append(math.degrees(math.acos(max(-1.0, min(1.0, (tu*u+tv*v)/(ts*ps))))))
    return {"uv_rmse": math.sqrt(sum(squared)/len(squared)),
            "speed_mae": sum(speeds)/len(speeds),
            "angular_mae_degrees": sum(angles)/len(angles) if angles else None,
            "angular_samples": len(angles), "samples": len(speeds)}


def train(config, *, seed=2026, count=48, length=160):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    import sklearn
    sequences = synthetic_sequences(seed=seed, count=count, length=length)
    groups = split_sequences(sequences)
    train_set, validation, test = [temporal_examples(group, config["lag_count"]) for group in groups]
    if len(train_set) < config["minimum_training_samples"]:
        raise ValueError("Entrenamiento insuficiente.")
    scaler = StandardScaler().fit([r.X for r in train_set])
    ridge = Ridge(alpha=config["ridge_alpha"]).fit(scaler.transform([r.X for r in train_set]), [r.y for r in train_set])
    def evaluate(rows):
        raw = ridge.predict(scaler.transform([r.X for r in rows]))
        predicted = [vector_prediction(r.target_turn, float(uv[0]), float(uv[1]), "ridge") for r, uv in zip(rows, raw)]
        return {"persistence": metrics([r.y for r in rows], [r.persistence for r in rows]),
                "ridge": metrics([r.y for r in rows], [(p.u, p.v) for p in predicted])}
    val_metrics = evaluate(validation)
    selected = min(val_metrics, key=lambda name: val_metrics[name]["uv_rmse"])
    report = {"data_source": "synthetic_simulation", "seed": seed,
              "description": "Viento virtual global de ocho direcciones, rampas/oscilaciones/rotaciones/persistencia/cambios ocasionales; no meteorologia real.",
              "split": {label: [s["sequence_id"] for s in group] for label, group in zip(("train", "validation", "test"), groups)},
              "training_samples": len(train_set), "validation": val_metrics, "test": evaluate(test),
              "selected_model": selected, "selection_rule": "minimum_validation_uv_rmse; test is report-only",
              "feature_names": list(feature_names(config["lag_count"])), "sklearn_version": sklearn.__version__}
    artifact = {"schema_version": "wind_predictor/1.0", "data_source": "synthetic_simulation",
                "selected_model": selected, "training_samples": len(train_set),
                "feature_names": report["feature_names"], "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
                "coefficients": ridge.coef_.tolist(), "intercept": ridge.intercept_.tolist(),
                "seed": seed, "split": report["split"], "selection_rule": report["selection_rule"]}
    # Medir tambien la politica realmente desplegada, incluida persistencia en
    # ventanas constantes. Nunca se utiliza test para seleccionar/refit.
    from tempfile import TemporaryDirectory
    from wind_prediction.model import WindPredictor
    with TemporaryDirectory(prefix="dcc_wind_eval_") as folder:
        path = Path(folder)/"model.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        for label, group in zip(("validation", "test"), groups[1:]):
            provider = WindPredictor(config, path)
            targets, predictions = [], []
            for sequence in group:
                history = []
                rows = sequence["samples"]
                for index, sample in enumerate(rows[:-1]):
                    history.append({key: sample[key] for key in ("turn", "u", "v")})
                    if len(history) < config["lag_count"]:
                        continue
                    prediction = provider.predict(history[-config["lag_count"]:])
                    predictions.append((prediction.u, prediction.v))
                    targets.append((rows[index+1]["u"], rows[index+1]["v"]))
            report[label]["selected_with_fallback"] = metrics(targets, predictions)
    return artifact, report, sequences


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/wind_prediction")
    args = parser.parse_args()
    config = json.loads((ROOT / "data/functional_scenario.json").read_text())["wind_prediction"]
    artifact, report, sequences = train(config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (("model.json", artifact), ("evaluation.json", report), ("sequences.json", sequences)):
        (args.output_dir / name).write_text(json.dumps(content, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"selected_model": report["selected_model"], "validation": report["validation"], "test": report["test"]}, indent=2))
