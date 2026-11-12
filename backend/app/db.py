"""Thin database adapter for PostgreSQL (psycopg 3) and SQLite.

SQL in the app is written once with `?` placeholders; the adapter converts
them for PostgreSQL. Timestamps are always written from Python as ISO-8601
UTC strings and read back as ISO strings on both engines.
"""
from __future__ import annotations

import datetime as dt
import glob
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings

log = logging.getLogger("speedo.db")
_SQL_LOG = os.environ.get("SPEEDO_SQL_LOG")  # dev aid: record every statement (used to check them against PostgreSQL)
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime | None = None) -> str:
    return (ts or utcnow()).astimezone(dt.timezone.utc).isoformat(timespec="microseconds")


def parse_ts(value: Any) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    s = str(value).replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _normalize(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, dt.datetime):
            v = iso(v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc))
        elif isinstance(v, dt.date):
            v = v.isoformat()
        out[k] = v
    return out


class Database:
    def __init__(self, url: str):
        self.url = url
        self.is_pg = url.startswith(("postgres://", "postgresql://"))
        self._lock = threading.RLock()
        self._local = threading.local()
        if self.is_pg:
            try:
                import psycopg  # type: ignore
                from psycopg.rows import dict_row  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("PostgreSQL selected but psycopg is not installed: pip install 'psycopg[binary]'") from e
            self._psycopg, self._dict_row = psycopg, dict_row
        else:
            path = url.replace("sqlite:///", "", 1)
            if path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._sqlite = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._sqlite.row_factory = sqlite3.Row
            self._sqlite.execute("PRAGMA journal_mode=WAL")
            self._sqlite.execute("PRAGMA foreign_keys=ON")
            self._sqlite.execute("PRAGMA busy_timeout=5000")

    # -- connections -----------------------------------------------------
    def _pg_conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = self._psycopg.connect(self.url, row_factory=self._dict_row, autocommit=True)
            self._local.conn = conn
        return conn

    def _log(self, sql: str) -> None:
        if _SQL_LOG:
            with open(_SQL_LOG, "a", encoding="utf-8") as fh:
                fh.write(" ".join(sql.split()) + "\n")

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_pg else sql

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        if self.is_pg:
            conn = self._pg_conn()
            with conn.transaction():
                yield self
        else:
            with self._lock:
                self._sqlite.execute("BEGIN")
                try:
                    yield self
                    self._sqlite.execute("COMMIT")
                except Exception:
                    self._sqlite.execute("ROLLBACK")
                    raise

    # -- queries -----------------------------------------------------------
    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        if self.is_pg:
            with self._pg_conn().cursor() as cur:
                cur.execute(self._sql(sql), params)
                return [_normalize(r) for r in cur.fetchall()] if cur.description else []
        self._log(sql)
        with self._lock:
            cur = self._sqlite.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        """Run a statement; returns affected row count."""
        if self.is_pg:
            with self._pg_conn().cursor() as cur:
                cur.execute(self._sql(sql), params)
                return cur.rowcount
        self._log(sql)
        with self._lock:
            return self._sqlite.execute(sql, params).rowcount

    def insert(self, table: str, values: dict) -> int:
        cols = list(values)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        params = [values[c] for c in cols]
        if self.is_pg:
            with self._pg_conn().cursor() as cur:
                cur.execute(self._sql(sql) + " RETURNING id", params)
                return cur.fetchone()["id"]
        self._log(sql)
        with self._lock:
            return self._sqlite.execute(sql, params).lastrowid

    def update(self, table: str, row_id: int, values: dict) -> int:
        if not values:
            return 0
        sets = ", ".join(f"{k} = ?" for k in values)
        return self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])

    def executescript(self, script: str) -> None:
        if self.is_pg:
            with self._pg_conn().cursor() as cur:
                cur.execute(script)
        else:
            with self._lock:
                self._sqlite.executescript(script)

    # -- migrations --------------------------------------------------------
    def migrate(self) -> list[str]:
        self.executescript(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)"
        )
        done = {r["version"] for r in self.all("SELECT version FROM schema_migrations")}
        applied = []
        for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
            version = os.path.basename(path)[:-4]
            if version in done:
                continue
            if "postgis" in version and not (self.is_pg and settings.enable_postgis):
                continue
            with open(path, encoding="utf-8") as fh:
                script = fh.read()
            if not self.is_pg:
                script = to_sqlite(script)
            log.info("applying migration %s", version)
            self.executescript(script)
            self.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, iso()))
            applied.append(version)
        return applied


def to_sqlite(script: str) -> str:
    script = re.sub(r"BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", script)
    script = re.sub(r"--\s*pg-only.*?--\s*end-pg-only", "", script, flags=re.S)
    return script


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(settings.database_url)
    return _db


def set_db(db: Database | None) -> None:
    global _db
    _db = db
