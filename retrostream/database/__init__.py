"""Connections are per transaction and safe across the application's threads."""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 4:
                raise RuntimeError("Database is newer than this application")
            if version == 0:
                db.executescript((Path(__file__).parent / "001_initial.sql").read_text())
                log.info("database_migration", extra={"version": 1})
                version = 1
            if version == 1:
                db.executescript((Path(__file__).parent / "002_auth.sql").read_text())
                log.info("database_migration", extra={"version": 2})
                version = 2
            if version == 2:
                db.executescript((Path(__file__).parent / "003_cache_preferences.sql").read_text())
                log.info("database_migration", extra={"version": 3})
                version = 3
            if version == 3:
                db.executescript((Path(__file__).parent / "004_cache_profile_versions.sql").read_text())
                log.info("database_migration", extra={"version": 4})

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql: str, args: tuple = ()) -> None:
        with self.connect() as db:
            db.execute(sql, args)
