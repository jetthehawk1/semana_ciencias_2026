"""Ejecuta los tests historicos y nuevos en una copia temporal de la aplicacion.

Los scripts originales usan __file__ para localizar data/ y algunos ensayos
exigen una copia. No se importan como tests de unittest: varios ejecutan sus
asserts al cargar o desde main(). Solo se usa la biblioteca estandar.
"""
from __future__ import annotations

import argparse
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
DATABASE_SCRIPTS = {"test_persona2_postgres.py", "test_persona2_end_to_end.py"}


def run_suite(root: Path, output: Path, *, pattern="test_*.py", require_db=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    scripts = sorted({*root.glob(pattern), *(root / "tests").rglob(pattern)})
    scripts = [p for p in scripts if p.is_file() and p.suffix == ".py"]
    if not scripts:
        raise ValueError("No se encontraron scripts de prueba.")
    has_driver = find_spec("psycopg") is not None
    if require_db and (not has_driver or not (
        os.environ.get("DCC_POSTGRES_BIN") or os.environ.get("DCC_TEST_DATABASE_URL")
    )):
        raise ValueError("--require-db necesita psycopg y DCC_POSTGRES_BIN o DCC_TEST_DATABASE_URL.")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
           "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}
    # Evita que un PYTHONPATH ajeno o Chagoya satisfaga imports de la copia.
    with TemporaryDirectory(prefix="dcc_suite_") as temp:
        copied = Path(temp) / "DisasterCommandCenter"
        shutil.copytree(root, copied, ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
            "*.pyc", "reports", "exports", ".env", "*.log",
        ))
        env["PYTHONPATH"] = os.pathsep.join((str(copied / "src"), str(copied)))
        for script in scripts:
            rel = script.relative_to(root).as_posix()
            record = {"script": rel, "status": "passed", "exit_code": None,
                      "unit_tests": 0, "skipped": 0}
            if script.name in DATABASE_SCRIPTS and not has_driver:
                record.update(status="skipped", skipped=1,
                              reason="PostgreSQL opcional: instala requirements-persona2-db.txt.")
                results.append(record)
                print(f"[SKIP] {rel}: {record['reason']}", flush=True)
                continue
            try:
                result = subprocess.run(
                    [sys.executable, "-B", str(copied / rel)], cwd=copied,
                    env=env, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=180,
                )
                log = result.stdout + result.stderr
                record["exit_code"] = result.returncode
                record["unit_tests"] = sum(int(n) for n in re.findall(r"Ran (\d+) tests? in", log))
                record["skipped"] = sum(int(n) for n in re.findall(r"skipped=(\d+)", log))
                if result.returncode or (require_db and record["skipped"]):
                    record["status"] = "failed"
            except subprocess.TimeoutExpired:
                log = "La prueba excedio el limite de 180 segundos.\n"
                record.update(status="failed", reason="timeout")
            log_name = rel.replace("/", "__") + ".log"
            (output / log_name).write_text(log, encoding="utf-8")
            record["log"] = log_name
            results.append(record)
            print(f"[{record['status'].upper()}] {rel} "
                  f"(unit_tests={record['unit_tests']}, skipped={record['skipped']})", flush=True)
            if record["status"] == "failed":
                print(log[-6000:], flush=True)
    report = {
        "scripts": results,
        "summary": {
            "scripts": len(results),
            "passed_scripts": sum(r["status"] == "passed" for r in results),
            "failed_scripts": sum(r["status"] == "failed" for r in results),
            "skipped_scripts": sum(r["status"] == "skipped" for r in results),
            "unit_tests": sum(r["unit_tests"] for r in results),
            "skipped": sum(r["skipped"] for r in results),
        },
        "isolated_copy": True, "headless": True,
    }
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_*.py", help="Patron de nombres de scripts")
    parser.add_argument("--require-db", action="store_true", help="Fallar si falta PostgreSQL o hay omisiones")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/integration_tests")
    args = parser.parse_args(argv)
    try:
        report = run_suite(ROOT, args.output_dir, pattern=args.pattern, require_db=args.require_db)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["summary"]["failed_scripts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
