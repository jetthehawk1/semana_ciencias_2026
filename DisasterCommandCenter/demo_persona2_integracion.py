"""Demostracion P2.7 sin ventana: simulador -> gateway -> IA -> PostgreSQL opcional."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from dcc_app.mode_scene import ModeSensorScene
from generar_entrega_persona2_15_1 import produce
from integration.persona2_gateway import SensorPredictionAdapter
from persona2.inference import train_prediction_service


def run_demo(training_folder: str | Path | None = None, *, repository=None) -> dict:
    with TemporaryDirectory(prefix="dcc_p27_demo_") as temp:
        folder = Path(temp)
        if training_folder is None:
            training_folder = folder / "training"
            produce(training_folder)
        service = train_prediction_service(training_folder)
        adapter = SensorPredictionAdapter(service)
        scene = ModeSensorScene(ROOT, kind="emergencia", mode="original")
        scene.start()
        predictions = adapter.update(scene)
        scene.toggle_pause()
        scene.step()
        paused_predictions = adapter.update(scene)
        if paused_predictions:
            raise AssertionError("No debe haber predicciones nuevas durante la pausa.")
        scene.toggle_pause()
        for _ in range(35):
            scene.step()
            predictions.extend(adapter.update(scene))
        report = {
            "source": {
                "run_id": scene.network.run_id, "dataset_kind": "synthetic_simulation",
                "schema_version": "1.0", "time_unit": "simulation_turn_not_seconds",
            },
            "model": service.metadata,
            "summary": {
                "sensor_count": len(scene.sensor_positions),
                "turn_count": len({row["turn"] for row in predictions}),
                "predictions": len(predictions),
                "positive_predictions": sum(row["predicted_fire_within_2_cells"] for row in predictions),
                "predictions_while_paused": len(paused_predictions),
            },
            "predictions": predictions,
            "notes": [
                "Demostracion funcional con datos sinteticos; no es una nueva evaluacion del modelo.",
                "La escena comparte escenario con el ejemplo de entrenamiento.",
                "El Decision Tree es la referencia experimental explicita, no un ganador seleccionado.",
                "No modifica motores, rutas ni estados de personas; no importa Pygame.",
            ],
        }
        if repository is not None:
            output = folder / "live_package"
            scene.export_readings(output)
            repository.initialize()
            imported = repository.import_package(output)
            repository.register_model(service.model_id, service.metadata)
            written = repository.save_predictions(predictions)
            core = {key: value for key, value in report.items() if key != "predictions"}
            report_id = repository.save_report(scene.network.run_id, "integration", core)
            report["database"] = {
                "import": imported, "prediction_write": written, "report_id": report_id,
                "counts": repository.counts(scene.network.run_id),
            }
        return report


def main():
    parser = argparse.ArgumentParser(description="P2.7: demo de predicciones sobre el simulador")
    parser.add_argument("--training-package", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--persist", action="store_true", help="Usar DCC_DATABASE_URL")
    parser.add_argument("--schema", default="persona2")
    args = parser.parse_args()
    repository = None
    try:
        if args.persist:
            from persona2.postgres_repository import PostgresRepository
            repository = PostgresRepository(schema=args.schema)
        report = run_demo(args.training_package, repository=repository)
    except ValueError as error:
        parser.error(str(error))
    except Exception as error:
        if args.persist:
            from psycopg import Error as PostgresError
            if isinstance(error, PostgresError):
                parser.error("Fallo PostgreSQL. Revisa disponibilidad y permisos de DCC_DATABASE_URL.")
        raise
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "informe_integracion.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({k: v for k, v in report.items() if k != "predictions"},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
