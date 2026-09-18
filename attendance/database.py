"""Attendance persistence — SQLite-first, PostgreSQL-capable.

Design mirrors the CamBrain pattern (raw SQL with two dialects where they
differ). Here the schema is deliberately written so
one DDL body works on both engines: TEXT UUID primary keys (no autoincrement),
``TIMESTAMPTZ`` as ISO-8601 UTC strings, ``BOOLEAN``/``DOUBLE PRECISION`` that
both backends accept. Timestamps are always written as UTC ISO-8601 with a ``Z``.

Never put face blobs/embeddings in rows; only ``template_ref`` (a secure local
path) is stored, per the data-model contract.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ATTENDANCE_DB_DSN overrides the default SQLite path. Postgres DSNs:
#   postgresql://user:pass@host:5432/dbname
DEFAULT_DB_PATH = os.path.join("attendance_data", "attendance.db")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Schema (single source of truth, both engines) ────────────────────────────
# Split statements so either engine evaluates them identically.
SCHEMA_STATEMENTS: List[str] = [
    """CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'teacher',
        active        BOOLEAN NOT NULL DEFAULT 1,
        created_at    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS students (
        id           TEXT PRIMARY KEY,
        student_code TEXT NOT NULL UNIQUE,
        full_name    TEXT NOT NULL,
        active       BOOLEAN NOT NULL DEFAULT 1,
        created_at   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS courses (
        id                 TEXT PRIMARY KEY,
        code               TEXT NOT NULL UNIQUE,
        name               TEXT NOT NULL,
        teacher_id         TEXT NOT NULL REFERENCES users(id),
        timezone           TEXT NOT NULL DEFAULT 'Asia/Kolkata',
        late_after_minutes INTEGER,
        created_at         TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS course_enrollments (
        id         TEXT PRIMARY KEY,
        course_id  TEXT NOT NULL REFERENCES courses(id),
        student_id TEXT NOT NULL REFERENCES students(id),
        active     BOOLEAN NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        UNIQUE (course_id, student_id)
    )""",
    """CREATE TABLE IF NOT EXISTS biometric_consents (
        id              TEXT PRIMARY KEY,
        student_id      TEXT NOT NULL REFERENCES students(id),
        consent_version TEXT NOT NULL,
        purpose         TEXT NOT NULL,
        consented_at    TEXT NOT NULL,
        revoked_at      TEXT,
        collected_by_id TEXT,
        evidence_ref    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS face_templates (
        id              TEXT PRIMARY KEY,
        student_id      TEXT NOT NULL REFERENCES students(id),
        template_ref    TEXT NOT NULL,
        model_version   TEXT NOT NULL,
        quality_meta    TEXT,
        enrolled_at     TEXT NOT NULL,
        revoked_at      TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS class_sessions (
        id         TEXT PRIMARY KEY,
        course_id  TEXT NOT NULL REFERENCES courses(id),
        starts_at  TEXT NOT NULL,
        ends_at    TEXT,
        status     TEXT NOT NULL DEFAULT 'scheduled',
        created_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attendance_records (
        id           TEXT PRIMARY KEY,
        session_id   TEXT NOT NULL REFERENCES class_sessions(id),
        student_id   TEXT NOT NULL REFERENCES students(id),
        status       TEXT NOT NULL,
        method       TEXT NOT NULL DEFAULT 'face',
        first_seen_at TEXT,
        marked_by    TEXT REFERENCES users(id),
        updated_at   TEXT NOT NULL,
        UNIQUE (session_id, student_id)
    )""",
    """CREATE TABLE IF NOT EXISTS attendance_events (
        id                 TEXT PRIMARY KEY,
        session_id         TEXT NOT NULL REFERENCES class_sessions(id),
        student_id         TEXT,
        recognition_status TEXT NOT NULL,
        action             TEXT NOT NULL,
        request_id         TEXT UNIQUE,
        actor_id           TEXT REFERENCES users(id),
        timestamp          TEXT NOT NULL,
        reason             TEXT,
        model_version      TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS audit_logs (
        id          TEXT PRIMARY KEY,
        actor_id    TEXT,
        action      TEXT NOT NULL,
        object_type TEXT NOT NULL,
        object_id   TEXT,
        reason      TEXT,
        before_s    TEXT,
        after_s     TEXT,
        timestamp   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS auth_tokens (
        id         TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        active     BOOLEAN NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS _schema_version (
        id          INTEGER PRIMARY KEY,
        version     INTEGER NOT NULL,
        applied_at  TEXT NOT NULL
    )""",
]

# Indexes — same on both engines.
SCHEMA_INDEXES: List[str] = [
    "CREATE INDEX IF NOT EXISTS idx_consents_student ON biometric_consents (student_id)",
    "CREATE INDEX IF NOT EXISTS idx_templates_student ON face_templates (student_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_course ON class_sessions (course_id)",
    "CREATE INDEX IF NOT EXISTS idx_records_session ON attendance_records (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_session ON attendance_events (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs (timestamp)",
]

SCHEMA_VERSION = 1


class AttendanceDB:
    """Thin connection manager for the attendance database.

    ``dsn``      Postgres URL (postgresql://...) or empty for SQLite.
    ``sqlite_path`` local file used when dsn is empty.
    """

    def __init__(self, dsn: Optional[str] = None, sqlite_path: Optional[str] = None):
        self.dsn = dsn or os.environ.get("ATTENDANCE_DB_DSN") or ""
        self.sqlite_path = sqlite_path or os.environ.get(
            "ATTENDANCE_DB_PATH", DEFAULT_DB_PATH)
        self.is_pg = self.dsn.startswith("postgresql://") or self.dsn.startswith("postgres://")
        if self.dsn and not self.is_pg:
            raise ValueError(f"Unsupported ATTENDANCE_DB_DSN scheme (wanted postgresql:// or empty for sqlite): {self.dsn}")

    def path_or_dsn(self) -> str:
        return self.dsn if self.is_pg else self.sqlite_path

    # ── connections ──────────────────────────────────────────────────────────
    def connect(self):
        if self.is_pg:
            import psycopg2
            return psycopg2.connect(self.dsn)
        if self.sqlite_path != ":memory:":
            os.makedirs(os.path.dirname(self.sqlite_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def row_to_dict(self, row) -> Optional[dict]:
        if row is None:
            return None
        return dict(row)

    # ── dialect ──────────────────────────────────────────────────────────────
    @staticmethod
    def _pg(sql: str) -> str:
        """Convert ``:name`` named params to psycopg2's ``%(name)s`` style."""
        return re.sub(r":([a-z_][a-z0-9_]*)", lambda m: "%(" + m.group(1) + ")s", sql)

    def _sql(self, sql: str) -> str:
        return self._pg(sql) if self.is_pg else sql

    def query(self, sql: str, params: Optional[dict] = None) -> List[dict]:
        conn = self.connect()
        try:
            cur = conn.execute(self._sql(sql), params or {})
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def query_one(self, sql: str, params: Optional[dict] = None) -> Optional[dict]:
        conn = self.connect()
        try:
            cur = conn.execute(self._sql(sql), params or {})
            row = cur.fetchone()
            return None if row is None else dict(row)
        finally:
            conn.close()

    def execute(self, sql: str, params: Optional[dict] = None) -> None:
        conn = self.connect()
        try:
            with conn:
                conn.execute(self._sql(sql), params or {})
        finally:
            conn.close()

    def transaction(self, fn=None):
        """Context manager (``with db.transaction() as conn``) returning the raw
        connection; commits on success, rolls back on exception. Also callable
        directly as db.transaction(fn)."""
        conn = self.connect()
        if fn is None:
            return _Transaction(conn)
        try:
            with conn:
                result = fn(conn)
            return result
        finally:
            conn.close()

    def tx_execute(self, conn, sql: str, params: Optional[dict] = None):
        """Like execute(), but for code running inside ``transaction()``. Returns
        a cursor that supports fetchone()/fetchall() on BOTH engines."""
        translated = self._sql(sql)
        if self.is_pg:
            cur = conn.cursor()
            cur.execute(translated, params or {})
            return cur
        return conn.execute(translated, params or {})

    # ── migrations ───────────────────────────────────────────────────────────
    def migrate(self) -> int:
        """Create schema + indexes idempotently; record version row. Returns version."""
        if self.is_pg:
            def _run(conn):
                for stmt in SCHEMA_STATEMENTS:
                    cur = conn.cursor(); cur.execute(stmt); cur.close()
                for stmt in SCHEMA_INDEXES:
                    cur = conn.cursor(); cur.execute(stmt); cur.close()
                cur = conn.cursor()
                cur.execute("SELECT version FROM _schema_version ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                cur.close()
                current = row[0] if row else 0
                if current < SCHEMA_VERSION:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO _schema_version (version, applied_at) VALUES (%(v)s, %(ts)s)",
                        {"v": SCHEMA_VERSION, "ts": _now_utc()})
                    cur.close()
                return max(current, SCHEMA_VERSION)

            return self.transaction(_run)

        conn = self.connect()
        try:
            with conn:
                for stmt in SCHEMA_STATEMENTS:
                    conn.execute(stmt)
                for stmt in SCHEMA_INDEXES:
                    conn.execute(stmt)
                row = conn.execute(
                    "SELECT version FROM _schema_version ORDER BY id DESC LIMIT 1").fetchone()
                current = row[0] if row else 0
                if current < SCHEMA_VERSION:
                    conn.execute(
                        "INSERT INTO _schema_version (version, applied_at) VALUES (?, ?)",
                        (SCHEMA_VERSION, _now_utc()))
                return max(current, SCHEMA_VERSION)
        finally:
            conn.close()

    # ── convenience ──────────────────────────────────────────────────────────
    def record_exists(self, table: str, column: str, value: str) -> bool:
        row = self.query_one(
            f"SELECT 1 FROM {table} WHERE {column} = :v",
            {"v": value},
        ) if not self.is_pg else self.query_one(
            f"SELECT 1 FROM {table} WHERE {column} = %(v)s",
            {"v": value},
        )
        return row is not None


class _Transaction:
    """Ensures commit/rollback on the raw sqlite/psycopg2 connection."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")