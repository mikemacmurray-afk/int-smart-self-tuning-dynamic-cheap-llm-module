"""MySQL/PostgreSQL storage backend for Smart LLM.

Uses SQLAlchemy Core for portability across MySQL and PostgreSQL.
Requires: pip install sqlalchemy aiomysql (or asyncpg for PostgreSQL)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult

try:
    from sqlalchemy import (
        Column, DateTime, Float, Integer, MetaData, String, Table,
        create_engine, select, update, delete, func, and_, text,
    )
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s) -> Optional[datetime]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s)


class MySQLBackend:
    """MySQL/PostgreSQL storage backend.

    Requires SQLAlchemy. Connection URL format:
    - MySQL: mysql+pymysql://user:pass@host:3306/dbname
    - PostgreSQL: postgresql+psycopg2://user:pass@host:5432/dbname
    """

    def __init__(self, url: str | None = None):
        if not HAS_SQLALCHEMY:
            raise ImportError(
                "MySQLBackend requires SQLAlchemy. Install with: "
                "pip install sqlalchemy pymysql  (or sqlalchemy asyncpg for PostgreSQL)"
            )
        self._url = url or "sqlite:///smart_llm.db"  # Fallback to SQLite via SQLAlchemy
        self._engine = None
        self._metadata = MetaData()

        # Define table schemas
        self._model_registry = Table(
            "model_registry", self._metadata,
            Column("model_id", String(120), primary_key=True),
            Column("tier", String(20), nullable=False),
            Column("provider", String(40), nullable=False),
            Column("status", String(20), nullable=False, default="candidate"),
            Column("quality_score", Float, nullable=True),
            Column("last_scanned_at", DateTime, nullable=True),
            Column("last_active_at", DateTime, nullable=True),
            Column("added_at", DateTime, nullable=False),
        )

        self._probe_cache = Table(
            "probe_cache", self._metadata,
            Column("model_id", String(120), primary_key=True),
            Column("response_ms", Integer, nullable=True),
            Column("status", String(20), nullable=False, default="unknown"),
            Column("probed_at", DateTime, nullable=False),
        )

        self._call_history = Table(
            "call_history", self._metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("model_id", String(120), nullable=False, index=True),
            Column("response_ms", Integer, nullable=True),
            Column("status", String(20), nullable=False, default="ok"),
            Column("called_at", DateTime, nullable=False, index=True),
            Column("day_of_week", Integer, nullable=False),
            Column("hour_of_day", Integer, nullable=False),
            Column("token_count", Integer, nullable=True),
        )

    def initialize(self) -> None:
        self._engine = create_engine(self._url, pool_pre_ping=True)
        self._metadata.create_all(self._engine)

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def _conn(self):
        if not self._engine:
            raise RuntimeError("MySQLBackend not initialized. Call initialize() first.")
        return self._engine.connect()

    # ── Registry ──────────────────────────────────────────────────────────────

    def get_active_models(self, tier: Optional[str] = None) -> list[ModelInfo]:
        t = self._model_registry
        stmt = select(t).where(t.c.status == "active")
        if tier:
            stmt = stmt.where(t.c.tier == tier)
        with self._conn() as conn:
            rows = conn.execute(stmt).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_all_models(self) -> list[ModelInfo]:
        with self._conn() as conn:
            rows = conn.execute(select(self._model_registry)).fetchall()
        return [self._row_to_model(r) for r in rows]

    def upsert_model(self, model: ModelInfo) -> None:
        t = self._model_registry
        with self._conn() as conn:
            # Try update first, then insert if no rows affected
            result = conn.execute(
                update(t).where(t.c.model_id == model.model_id).values(
                    tier=model.tier,
                    provider=model.provider,
                    status=model.status,
                    quality_score=model.quality_score,
                    last_scanned_at=model.last_scanned_at,
                    last_active_at=model.last_active_at,
                )
            )
            if result.rowcount == 0:
                conn.execute(t.insert().values(
                    model_id=model.model_id,
                    tier=model.tier,
                    provider=model.provider,
                    status=model.status,
                    quality_score=model.quality_score,
                    last_scanned_at=model.last_scanned_at,
                    last_active_at=model.last_active_at,
                    added_at=model.added_at,
                ))
            conn.commit()

    def retire_model(self, model_id: str) -> None:
        t = self._model_registry
        with self._conn() as conn:
            conn.execute(update(t).where(t.c.model_id == model_id).values(status="retired"))
            conn.commit()

    def count_models(self) -> int:
        with self._conn() as conn:
            row = conn.execute(select(func.count()).select_from(self._model_registry)).fetchone()
        return row[0]

    # ── Probe cache ───────────────────────────────────────────────────────────

    def get_probe(self, model_id: str) -> Optional[ProbeResult]:
        t = self._probe_cache
        with self._conn() as conn:
            row = conn.execute(select(t).where(t.c.model_id == model_id)).fetchone()
        return self._row_to_probe(row) if row else None

    def get_all_probes(self) -> list[ProbeResult]:
        with self._conn() as conn:
            rows = conn.execute(select(self._probe_cache)).fetchall()
        return [self._row_to_probe(r) for r in rows]

    def upsert_probe(self, probe: ProbeResult) -> None:
        t = self._probe_cache
        with self._conn() as conn:
            result = conn.execute(
                update(t).where(t.c.model_id == probe.model_id).values(
                    response_ms=probe.response_ms,
                    status=probe.status,
                    probed_at=probe.probed_at,
                )
            )
            if result.rowcount == 0:
                conn.execute(t.insert().values(
                    model_id=probe.model_id,
                    response_ms=probe.response_ms,
                    status=probe.status,
                    probed_at=probe.probed_at,
                ))
            conn.commit()

    # ── Call history ──────────────────────────────────────────────────────────

    def record_call(self, record: CallRecord) -> None:
        t = self._call_history
        with self._conn() as conn:
            conn.execute(t.insert().values(
                model_id=record.model_id,
                response_ms=record.response_ms,
                status=record.status,
                called_at=record.called_at,
                day_of_week=record.day_of_week,
                hour_of_day=record.hour_of_day,
                token_count=record.token_count,
            ))
            conn.commit()

    def get_history(self, model_id: str, since: datetime) -> list[CallRecord]:
        t = self._call_history
        with self._conn() as conn:
            rows = conn.execute(
                select(t).where(
                    and_(t.c.model_id == model_id, t.c.called_at >= since)
                ).order_by(t.c.called_at.desc())
            ).fetchall()
        return [self._row_to_call(r) for r in rows]

    def get_all_history(self, since: datetime) -> list[CallRecord]:
        t = self._call_history
        with self._conn() as conn:
            rows = conn.execute(
                select(t).where(t.c.called_at >= since).order_by(t.c.called_at.desc())
            ).fetchall()
        return [self._row_to_call(r) for r in rows]

    def prune_old_records(self, before: datetime) -> int:
        t = self._call_history
        with self._conn() as conn:
            result = conn.execute(delete(t).where(t.c.called_at < before))
            conn.commit()
        return result.rowcount

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status_summary(self) -> dict:
        t = self._model_registry
        with self._conn() as conn:
            total = conn.execute(select(func.count()).select_from(t)).fetchone()[0]
            active_free = conn.execute(
                select(func.count()).select_from(t).where(and_(t.c.status == "active", t.c.tier == "free"))
            ).fetchone()[0]
            active_cheap = conn.execute(
                select(func.count()).select_from(t).where(and_(t.c.status == "active", t.c.tier == "cheap"))
            ).fetchone()[0]
            active_paid = conn.execute(
                select(func.count()).select_from(t).where(and_(t.c.status == "active", t.c.tier == "paid"))
            ).fetchone()[0]
            active_local = conn.execute(
                select(func.count()).select_from(t).where(and_(t.c.status == "active", t.c.tier == "local"))
            ).fetchone()[0]
            total_probes = conn.execute(
                select(func.count()).select_from(self._probe_cache)
            ).fetchone()[0]
            total_history = conn.execute(
                select(func.count()).select_from(self._call_history)
            ).fetchone()[0]
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
    def _row_to_model(row) -> ModelInfo:
        return ModelInfo(
            model_id=row.model_id,
            tier=row.tier,
            provider=row.provider,
            status=row.status,
            quality_score=row.quality_score,
            last_scanned_at=_str_to_dt(row.last_scanned_at),
            last_active_at=_str_to_dt(row.last_active_at),
            added_at=_str_to_dt(row.added_at) or datetime.now(),
        )

    @staticmethod
    def _row_to_probe(row) -> ProbeResult:
        return ProbeResult(
            model_id=row.model_id,
            response_ms=row.response_ms,
            status=row.status,
            probed_at=_str_to_dt(row.probed_at) or datetime.now(),
        )

    @staticmethod
    def _row_to_call(row) -> CallRecord:
        return CallRecord(
            model_id=row.model_id,
            response_ms=row.response_ms,
            status=row.status,
            called_at=_str_to_dt(row.called_at) or datetime.now(),
            day_of_week=row.day_of_week,
            hour_of_day=row.hour_of_day,
            token_count=row.token_count,
        )
