"""P2.6: repositorio PostgreSQL; cada escritura es una transaccion explicita."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .ingestion import DEFAULT_SENSORS_PATH, read_sensor_package


def _fingerprint(value) -> str:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PostgresRepository:
    """No conecta al importar ni escribe durante frames de Pygame.

    DSN puede pasarse explicitamente o en DCC_DATABASE_URL. El esquema
    por defecto es persona2. Ningun metodo borra o reemplaza datos previos.
    """

    def __init__(self, dsn: str | None = None, *, schema: str = "persona2"):
        self.dsn = dsn if dsn is not None else os.environ.get("DCC_DATABASE_URL")
        if not self.dsn:
            raise ValueError("Configura DCC_DATABASE_URL para usar PostgreSQL.")
        if not isinstance(schema, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("Nombre de esquema no valido.")
        self.schema = schema

    def _connect(self):
        return psycopg.connect(self.dsn, connect_timeout=5)

    def _query(self, template):
        return sql.SQL(template).format(schema=sql.Identifier(self.schema))

    def initialize(self):
        path = Path(__file__).with_name("sql") / "001_initial.sql"
        with self._connect() as conn:
            conn.execute(self._query(path.read_text(encoding="utf-8-sig")))

    def import_package(
        self, folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH,
        every_n_turns: int = 1,
    ) -> dict:
        if type(every_n_turns) is not int or every_n_turns < 1:
            raise ValueError("every_n_turns debe ser entero positivo.")
        package = read_sensor_package(folder, sensors_path=sensors_path)
        manifest = package["manifest"]
        rows = package["labelled_rows"]
        run_id = manifest["run_id"]
        package_hash = _fingerprint({
            "manifest": manifest, "rows": sorted(rows, key=lambda r: (r["turn"], r["sensor_id"]))
        })
        first, last = manifest["first_turn"], manifest["last_turn"]
        selected = [
            row for row in rows
            if (row["turn"] - first) % every_n_turns == 0
            or row["turn"] == last or row["alarm"]
        ]
        with self._connect() as conn:
            inserted = conn.execute(self._query("""
                INSERT INTO {schema}.simulations
                (run_id, schema_version, dataset_kind, manifest, package_hash, sampling_interval)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING
                RETURNING run_id
            """), (
                run_id, manifest["schema_version"], manifest["dataset_kind"],
                Jsonb(manifest), package_hash, every_n_turns,
            )).fetchone()
            existing = conn.execute(self._query("""
                SELECT package_hash, sampling_interval FROM {schema}.simulations
                WHERE run_id = %s FOR UPDATE
            """), (run_id,)).fetchone()
            if existing != (package_hash, every_n_turns):
                raise ValueError("run_id ya existe con datos o politica de muestreo diferentes.")
            if inserted:
                sensors = {row["sensor_id"]: row for row in rows}
                with conn.cursor() as cursor:
                    cursor.executemany(self._query("""
                        INSERT INTO {schema}.sensors (run_id, sensor_id, x, y, building_id)
                        VALUES (%s, %s, %s, %s, %s)
                    """), [
                        (run_id, sid, row["x"], row["y"], row["building_id"])
                        for sid, row in sensors.items()
                    ])
                    cursor.executemany(self._query("""
                        INSERT INTO {schema}.readings
                        (run_id, turn, sensor_id, temperature_c, smoke_index, alarm, fire_within_2_cells)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """), [
                        tuple(row[key] for key in (
                            "run_id", "turn", "sensor_id", "temperature_c", "smoke_index",
                            "alarm", "fire_within_2_cells",
                        )) for row in selected
                    ])
                    cursor.executemany(self._query("""
                        INSERT INTO {schema}.events (run_id, turn, sensor_id, kind, details)
                        VALUES (%s, %s, %s, 'sensor_alarm', %s)
                    """), [
                        (run_id, row["turn"], row["sensor_id"], Jsonb({
                            "temperature_c": row["temperature_c"], "smoke_index": row["smoke_index"]
                        })) for row in selected if row["alarm"]
                    ])
            stored = conn.execute(self._query(
                "SELECT count(*) FROM {schema}.readings WHERE run_id = %s"
            ), (run_id,)).fetchone()[0]
        return {
            "run_id": run_id, "inserted": inserted is not None,
            "original_records": len(rows), "stored_readings": stored,
            "sampling_interval": every_n_turns,
        }

    def readings(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(self._query("""
                    SELECT sim.schema_version, r.run_id, r.turn, r.sensor_id, s.x, s.y, s.building_id,
                           r.temperature_c, r.smoke_index, r.alarm, r.fire_within_2_cells
                    FROM {schema}.readings r JOIN {schema}.sensors s
                    USING (run_id, sensor_id) JOIN {schema}.simulations sim USING (run_id)
                    WHERE r.run_id = %s ORDER BY r.turn, r.sensor_id
                """), (run_id,))
                return cursor.fetchall()

    def save_report(self, run_id: str, kind: str, report: dict) -> str:
        if kind not in {"eda", "baseline", "comparison", "integration"}:
            raise ValueError("Tipo de informe no valido.")
        if (not isinstance(report, dict) or not isinstance(report.get("source"), dict)
                or report["source"].get("run_id") != run_id):
            raise ValueError("El informe debe identificar la misma ejecucion en source.run_id.")
        report_id = _fingerprint({"run_id": run_id, "kind": kind, "report": report})
        with self._connect() as conn:
            conn.execute(self._query("""
                INSERT INTO {schema}.reports (report_id, run_id, kind, report)
                VALUES (%s, %s, %s, %s) ON CONFLICT (report_id) DO NOTHING
            """), (report_id, run_id, kind, Jsonb(report)))
        return report_id

    def register_model(self, model_id: str, metadata: dict):
        if not isinstance(model_id, str) or not model_id.strip() or not isinstance(metadata, dict):
            raise ValueError("Modelo o metadatos no validos.")
        _fingerprint(metadata)
        with self._connect() as conn:
            conn.execute(self._query("""
                INSERT INTO {schema}.models (model_id, metadata) VALUES (%s, %s)
                ON CONFLICT (model_id) DO NOTHING
            """), (model_id, Jsonb(metadata)))
            current = conn.execute(self._query("""
                SELECT metadata FROM {schema}.models WHERE model_id = %s FOR UPDATE
            """), (model_id,)).fetchone()[0]
            if current != metadata:
                raise ValueError("model_id ya existe con metadatos diferentes.")

    def save_predictions(self, predictions: list[dict]) -> dict:
        """Atomicidad de todo el lote; no permite cambiar una prediccion previa."""
        if not isinstance(predictions, list) or not predictions:
            raise ValueError("Se requiere una lista no vacia de predicciones.")
        keys = set()
        for prediction in predictions:
            if (not isinstance(prediction, dict)
                    or not {"run_id", "turn", "sensor_id", "model_id",
                            "predicted_fire_within_2_cells"}.issubset(prediction)
                    or type(prediction["predicted_fire_within_2_cells"]) is not bool):
                raise ValueError("Prediccion no valida.")
            if (type(prediction["turn"]) is not int or prediction["turn"] < 0
                    or any(not isinstance(prediction[k], str) or not prediction[k].strip()
                           for k in ("run_id", "sensor_id", "model_id"))):
                raise ValueError("Identificadores o turno de prediccion no validos.")
            key = tuple(prediction[k] for k in ("run_id", "turn", "sensor_id", "model_id"))
            if key in keys:
                raise ValueError("Prediccion duplicada en el lote.")
            keys.add(key)
        inserted = 0
        with self._connect() as conn:
            for prediction in predictions:
                key = tuple(prediction[k] for k in ("run_id", "turn", "sensor_id", "model_id"))
                value = prediction["predicted_fire_within_2_cells"]
                result = conn.execute(self._query("""
                    INSERT INTO {schema}.predictions
                    (run_id, turn, sensor_id, model_id, predicted_fire_within_2_cells)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, turn, sensor_id, model_id) DO NOTHING RETURNING model_id
                """), (*key, value)).fetchone()
                previous = conn.execute(self._query("""
                    SELECT predicted_fire_within_2_cells FROM {schema}.predictions
                    WHERE run_id=%s AND turn=%s AND sensor_id=%s AND model_id=%s FOR UPDATE
                """), key).fetchone()[0]
                if previous != value:
                    raise ValueError("La prediccion existente tiene otro valor; usa otro model_id.")
                inserted += result is not None
        return {"received": len(predictions), "inserted": inserted}

    def counts(self, run_id: str) -> dict:
        with self._connect() as conn:
            return {
                table: conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{} WHERE run_id=%s").format(
                        sql.Identifier(self.schema), sql.Identifier(table)
                    ), (run_id,)
                ).fetchone()[0]
                for table in ("simulations", "sensors", "readings", "events", "predictions", "reports")
            }


def main():
    parser = argparse.ArgumentParser(description="P2.6: importar paquete validado a PostgreSQL")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--schema", default="persona2")
    parser.add_argument("--every-n-turns", type=int, default=1)
    parser.add_argument("--sensors-path", type=Path, default=DEFAULT_SENSORS_PATH)
    args = parser.parse_args()
    try:
        repository = PostgresRepository(schema=args.schema)
        # Validar antes de crear el esquema o escribir.
        read_sensor_package(args.folder, sensors_path=args.sensors_path)
        repository.initialize()
        result = repository.import_package(
            args.folder, sensors_path=args.sensors_path, every_n_turns=args.every_n_turns
        )
    except psycopg.Error:
        parser.error("Fallo PostgreSQL. Revisa disponibilidad y permisos de DCC_DATABASE_URL.")
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
