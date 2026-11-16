"""Connexions SQLite, transactions et migrations (ARCHITECTURE section 6)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

MIGRATIONS_PACKAGE = "neurocoach.infra.migrations"


class Database:
    """Une connexion par unite de travail ; ecritures en ``BEGIN IMMEDIATE``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None : les transactions sont ouvertes explicitement ci-dessous.
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def schema_version(self) -> int:
        conn = self.connect()
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

    def migrate(self) -> int:
        """Applique les migrations manquantes dans l'ordre ; renvoie la version finale."""
        scripts = sorted(
            (
                item
                for item in resources.files(MIGRATIONS_PACKAGE).iterdir()
                if item.name.endswith(".sql")
            ),
            key=lambda item: item.name,
        )
        conn = self.connect()
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            for script in scripts:
                number = int(script.name.split("_", 1)[0])
                if number <= current:
                    continue
                sql = script.read_text(encoding="utf-8")
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
                current = number
            return current
        finally:
            conn.close()
