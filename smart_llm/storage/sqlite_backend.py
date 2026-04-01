"""SQLite storage backend for Smart LLM.

Default backend. Uses sqlite3 (stdlib) for zero-dependency local storage.
WAL mode enabled for concurrent read performance.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS model_registry (
    model_id    TEXT PRIMARY KEY,
    tier        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'candidate',
    quality_score REAL,
    last_scanned_at TEXT,
    last_active_at  TEXT,
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probe_cache (
    model_id    TEXT PRIMARY KEY,
    response_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'unknown',
    probed_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    TEXT NOT NULL,
    response_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'ok',
    called_at   TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    hour_of_day INTEGER NOT NULL,
    token_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_call_history_model ON call_history(model_id);
CREATE INDEX IF NOT EXISTS idx_call_history_called ON call_history(called_at);
"""


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


class SQLiteBackend:
    """SQLite storage backend (default).

    Uses stdlib sqlite3 — no external dependencies.
    WAL mode for concurrent reads. One connection for lifetime of backend.
    """

    def __init__(self, path: str | None = None):
        self._path = path or "smart_llm.db"
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE_TABLES)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("SQLiteBackend not initialized. Call initialize() first.")
        return self._conn

    # ── Registry ──────────────────────────────────────────────────────────────

    def get_active_models(self, tier: Optional[str] = None) -> list[ModelInfo]:
        conn = self._ensure_conn()
        if tier:
            rows = conn.execute(
                "SELECT * FROM model_registry WHERE status = 'active' AND tier = ?",
                (tier,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM model_registry WHERE status = 'active'"
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_all_models(self) -> list[ModelInfo]:
        conn = self._ensure_conn()
        rows = conn.execute("SELECT * FROM model_registry").fetchall()
        return [self._row_to_model(r) for r in rows]

    def upsert_model(self, model: ModelInfo) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT INTO model_registry
               (model_id, tier, provider, status, quality_score,
                last_scanned_at, last_active_at, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(model_id) DO UPDATE SET
                 tier = excluded.tier,
                 provider = excluded.provider,
                 status = excluded.status,
                 quality_score = excluded.quality_score,
                 last_scanned_at = excluded.last_scanned_at,
                 last_active_at = excluded.last_active_at""",
            (
                model.model_id, model.tier, model.provider, model.status,
                model.quality_score,
                _dt_to_str(model.last_scanned_at),
                _dt_to_str(model.last_active_at),
                _dt_to_str(model.added_at),
            ),
        )
        conn.commit()

    def retire_model(self, model_id: str) -> None:
        conn = self._ensure_conn()
        conn.execute(
            "UPDATE model_registry SET status = 'retired' WHERE model_id = ?",
            (model_id,),
        )
        conn.commit()

    def count_models(self) -> int:
        conn = self._ensure_conn()
        row = conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()
        return row[0]

    # ── Probe cache ───────────────────────────────────────────────────────────

    def get_probe(self, model_id: str) -> Optional[ProbeResult]:
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT * FROM probe_cache WHERE model_id = ?", (model_id,)
        ).fetchone()
        return self._row_to_probe(row) if row else None

    def get_all_probes(self) -> list[ProbeResult]:
        conn = self._ensure_conn()
        rows = conn.execute("SELECT * FROM probe_cache").fetchall()
        return [self._row_to_probe(r) for r in rows]

    def upsert_probe(self, probe: ProbeResult) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT INTO probe_cache (model_id, response_ms, status, probed_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(model_id) DO UPDATE SET
                 response_ms = excluded.response_ms,
                 status = excluded.status,
                 probed_at = excluded.probed_at""",
            (probe.model_id, probe.response_ms, probe.status, _dt_to_str(probe.probed_at)),
        )
        conn.commit()

    # ── Call history ──────────────────────────────────────────────────────────

    def record_call(self, record: CallRecord) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT INTO call_history
               (model_id, response_ms, status, called_at, day_of_week, hour_of_day, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.model_id, record.response_ms, record.status,
                _dt_to_str(record.called_at),
                record.day_of_week, record.hour_of_day, record.token_count,
            ),
        )
        conn.commit()

    def get_history(self, model_id: str, since: datetime) -> list[CallRecord]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM call_history WHERE model_id = ? AND called_at >= ? ORDER BY called_at DESC",
            (model_id, _dt_to_str(since)),
        ).fetchall()
        return [self._row_to_call(r) for r in rows]

    def get_all_history(self, since: datetime) -> list[CallRecord]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM call_history WHERE called_at >= ? ORDER BY called_at DESC",
            (_dt_to_str(since),),
        ).fetchall()
        return [self._row_to_call(r) for r in rows]

    def prune_old_records(self, before: datetime) -> int:
        conn = self._ensure_conn()
        cursor = conn.execute(
            "DELETE FROM call_history WHERE called_at < ?",
            (_dt_to_str(before),),
        )
        conn.commit()
        return cursor.rowcount

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status_summary(self) -> dict:
        conn = self._ensure_conn()
        total = conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0]
        active_free = conn.execute(
            "SELECT COUNT(*) FROM model_registry WHERE status='active' AND tier='free'"
        ).fetchone()[0]
        active_cheap = conn.execute(
            "SELECT COUNT(*) FROM model_registry WHERE status='active' AND tier='cheap'"
        ).fetchone()[0]
        active_paid = conn.execute(
            "SELECT COUNT(*) FROM model_registry WHERE status='active' AND tier='paid'"
        ).fetchone()[0]
        active_local = conn.execute(
            "SELECT COUNT(*) FROM model_registry WHERE status='active' AND tier='local'"
        ).fetchone()[0]
        total_probes = conn.execute("SELECT COUNT(*) FROM probe_cache").fetchone()[0]
        total_history = conn.execute("SELECT COUNT(*) FROM call_history").fetchone()[0]
        return {
            "total_models": total,
            "active_free": active_free,
            "active_cheap": active_cheap,
            "active_paid": active_paid,
            "active_local": active_local,
            "total_probes": total_probes,
            "total_history": total_history,
        }

    # ── Row mappers ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ModelInfo:
        return ModelInfo(
            model_id=row["model_id"],
            tier=row["tier"],
            provider=row["provider"],
            status=row["status"],
            quality_score=row["quality_score"],
            last_scanned_at=_str_to_dt(row["last_scanned_at"]),
            last_active_at=_str_to_dt(row["last_active_at"]),
            added_at=_str_to_dt(row["added_at"]) or datetime.now(),
        )

    @staticmethod
    def _row_to_probe(row: sqlite3.Row) -> ProbeResult:
        return ProbeResult(
            model_id=row["model_id"],
            response_ms=row["response_ms"],
            status=row["status"],
            probed_at=_str_to_dt(row["probed_at"]) or datetime.now(),
        )

    @staticmethod
    def _row_to_call(row: sqlite3.Row) -> CallRecord:
        return CallRecord(
            model_id=row["model_id"],
            response_ms=row["response_ms"],
            status=row["status"],
            called_at=_str_to_dt(row["called_at"]) or datetime.now(),
            day_of_week=row["day_of_week"],
            hour_of_day=row["hour_of_day"],
            token_count=row["token_count"],
        )
