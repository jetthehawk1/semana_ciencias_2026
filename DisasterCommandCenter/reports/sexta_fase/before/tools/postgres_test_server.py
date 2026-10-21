"""Servidor PostgreSQL temporal para pruebas; no instala ni cambia servicios."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import unittest

from psycopg.conninfo import make_conninfo


class PostgresTestServer:
    """Usa DCC_TEST_DATABASE_URL o crea un cluster con DCC_POSTGRES_BIN.

    No imprime DSN ni contrasenas. Cada suite debe usar esquemas exclusivos.
    """

    def __enter__(self):
        external = os.environ.get("DCC_TEST_DATABASE_URL")
        self.temp = None
        if external:
            self.dsn = external
            return self
        binaries = os.environ.get("DCC_POSTGRES_BIN")
        if not binaries:
            raise unittest.SkipTest(
                "PostgreSQL: define DCC_POSTGRES_BIN o DCC_TEST_DATABASE_URL."
            )
        suffix = ".exe" if os.name == "nt" else ""
        self.pg_ctl = str(Path(binaries) / ("pg_ctl" + suffix))
        initdb = str(Path(binaries) / ("initdb" + suffix))
        if not Path(self.pg_ctl).is_file() or not Path(initdb).is_file():
            raise RuntimeError("No se encontraron initdb/pg_ctl en DCC_POSTGRES_BIN.")
        self.temp = tempfile.TemporaryDirectory(prefix="dcc_pg_test_")
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        password = secrets.token_urlsafe(32)
        password_file = self.root / "password.txt"
        password_file.write_text(password, encoding="utf-8")
        self.env = os.environ.copy()
        self.env["PATH"] = str(Path(binaries)) + os.pathsep + self.env.get("PATH", "")
        self.started = False
        try:
            self._run([
                initdb, "-D", str(self.data), "-U", "dcc_test", "-E", "UTF8", "--locale=C",
                "--auth-host=scram-sha-256", "--auth-local=scram-sha-256",
                "--pwfile=" + str(password_file),
            ])
            password_file.unlink()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            self._run([
                self.pg_ctl, "-D", str(self.data), "-l", str(self.root / "server.log"),
                "-o", f"-h 127.0.0.1 -p {port}", "-w", "start",
            ])
            self.started = True
            self.dsn = make_conninfo(
                host="127.0.0.1", port=port, dbname="postgres",
                user="dcc_test", password=password, connect_timeout=5,
            )
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _run(self, command):
        # Los hijos de pg_ctl pueden heredar pipes en Windows: usar un
        # archivo evita esperar indefinidamente al cierre de stdout/stderr.
        with (self.root / "commands.log").open("ab") as log:
            result = subprocess.run(
                command, env=self.env, stdout=log, stderr=log, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        if result.returncode:
            # Los argumentos no contienen la contrasena; la salida se omite por privacidad.
            raise RuntimeError(f"PostgreSQL: fallo {Path(command[0]).name} (codigo {result.returncode}).")

    def __exit__(self, *_):
        if self.temp is None:
            return
        try:
            if self.started or (self.data / "postmaster.pid").exists():
                self._run([self.pg_ctl, "-D", str(self.data), "-m", "fast", "-w", "stop"])
        finally:
            # Solo se elimina el directorio temporal creado por esta instancia.
            if (self.root.is_relative_to(Path(tempfile.gettempdir()).resolve())
                    and self.root.name.startswith("dcc_pg_test_")
                    and not (self.data / "postmaster.pid").exists()):
                self.temp.cleanup()
