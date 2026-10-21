"""Comprobacion reproducible P2.6/P2.7 sobre PostgreSQL temporal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import psycopg
from demo_persona2_integracion import run_demo
from generar_entrega_persona2_15_1 import produce
from persona2.baseline import evaluate_baseline
from persona2.eda import analyze_sensor_package
from persona2.model_comparison import compare_models
from persona2.postgres_repository import PostgresRepository
from tools.postgres_test_server import PostgresTestServer


def verify(repository: PostgresRepository, output_dir: str | Path) -> dict:
    output = Path(output_dir)
    with TemporaryDirectory(prefix="dcc_p2_verify_") as temp:
        package = Path(temp) / "package"
        produce(package)
        report = run_demo(package, repository=repository)
        run_id = report["source"]["run_id"]
        for kind, analysis in (
            ("eda", analyze_sensor_package(package)),
            ("baseline", evaluate_baseline(package)),
            ("comparison", compare_models(package)),
        ):
            repository.save_report(run_id, kind, analysis)
        repeated = repository.import_package(package)
        counts = repository.counts(run_id)
        if repeated["inserted"] or counts != {
            "simulations": 1, "sensors": 12, "readings": 432,
            "events": 126, "predictions": 432, "reports": 4,
        }:
            raise AssertionError("La verificacion del ejemplo de referencia no coincide.")
        report["database"]["counts"] = counts
        report["database"]["repeated_import"] = repeated
        with repository._connect() as conn:
            server_version = conn.execute("SHOW server_version").fetchone()[0]
        persistence = {
            "postgresql_version": server_version, "dataset_kind": "synthetic_simulation",
            "counts": counts, "repeated_import_inserted": repeated["inserted"],
            "model_id": report["model"]["model_id"],
            "notes": [
                "Resultado obtenido con PostgreSQL real, sin mocks.",
                "La CLI usa un cluster temporal o DCC_TEST_DATABASE_URL; no imprime credenciales.",
            ],
        }
    output.mkdir(parents=True, exist_ok=True)
    (output / "informe_integracion.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "informe_persistencia.json").write_text(
        json.dumps(persistence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return {"summary": report["summary"], "persistence": persistence}


def main():
    parser = argparse.ArgumentParser(description="Verificar P2.6/P2.7 con PostgreSQL real")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/persona2_p2_7")
    args = parser.parse_args()
    with PostgresTestServer() as server:
        repository = PostgresRepository(server.dsn, schema="dcc_p2_verification")
        result = verify(repository, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
