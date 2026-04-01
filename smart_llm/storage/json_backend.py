"""JSON file storage backend for Smart LLM.

Stores all state in a single JSON file. Thread-safe via threading.Lock.
Best for: small projects, scripts, development, debugging (easy to inspect).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Optional

from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO string for JSON serialisation."""
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    """Convert ISO string back to datetime."""
    return datetime.fromisoformat(s) if s else None


def _model_to_dict(m: ModelInfo) -> dict:
    return {
        "model_id": m.model_id,
        "tier": m.tier,
        "provider": m.provider,
        "status": m.status,
        "quality_score": m.quality_score,
        "last_scanned_at": _dt_to_str(m.last_scanned_at),
        "last_active_at": _dt_to_str(m.last_active_at),
        "added_at": _dt_to_str(m.added_at),
    }


def _dict_to_model(d: dict) -> ModelInfo:
    return ModelInfo(
        model_id=d["model_id"],
        tier=d["tier"],
        provider=d["provider"],
        status=d["status"],
        quality_score=d.get("quality_score"),
        last_scanned_at=_str_to_dt(d.get("last_scanned_at")),
        last_active_at=_str_to_dt(d.get("last_active_at")),
        added_at=_str_to_dt(d.get("added_at")) or datetime.now(),
    )


def _probe_to_dict(p: ProbeResult) -> dict:
    return {
        "model_id": p.model_id,
        "response_ms": p.response_ms,
        "status": p.status,
        "probed_at": _dt_to_str(p.probed_at),
    }


def _dict_to_probe(d: dict) -> ProbeResult:
    return ProbeResult(
        model_id=d["model_id"],
        response_ms=d.get("response_ms"),
        status=d.get("status", "unknown"),
        probed_at=_str_to_dt(d.get("probed_at")) or datetime.now(),
    )


def _call_to_dict(c: CallRecord) -> dict:
    return {
        "model_id": c.model_id,
        "response_ms": c.response_ms,
        "status": c.status,
        "called_at": _dt_to_str(c.called_at),
        "day_of_week": c.day_of_week,
        "hour_of_day": c.hour_of_day,
        "token_count": c.token_count,
    }


def _dict_to_call(d: dict) -> CallRecord:
    return CallRecord(
        model_id=d["model_id"],
        response_ms=d.get("response_ms"),
        status=d.get("status", "ok"),
        called_at=_str_to_dt(d.get("called_at")) or datetime.now(),
        day_of_week=d.get("day_of_week", -1),
        hour_of_day=d.get("hour_of_day", -1),
        token_count=d.get("token_count"),
    )


class JSONBackend:
    """JSON file storage backend.

    All state is stored in a single JSON file with three sections:
    - models: dict[model_id → ModelInfo]
    - probes: dict[model_id → ProbeResult]
    - history: list[CallRecord]

    Thread-safe via threading.Lock. Writes on every mutation.
    """

    def __init__(self, path: str | None = None):
        self._path = path or "smart_llm_state.json"
        self._lock = threading.Lock()
        self._data: dict = {"models": {}, "probes": {}, "history": []}

    def initialize(self) -> None:
        """Load existing data from file, or create empty state."""
        with self._lock:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = {"models": {}, "probes": {}, "history": []}
                self._save()

    def close(self) -> None:
        """Flush data to disk."""
        with self._lock:
            self._save()

    def _save(self) -> None:
        """Write state to disk. Must be called with _lock held."""
        # Atomic write: write to temp file then rename
        tmp_path = self._path + ".tmp"
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, default=str)
        # On Windows, need to remove target first if it exists
        if os.path.exists(self._path):
            os.replace(tmp_path, self._path)
        else:
            os.rename(tmp_path, self._path)

    # ── Registry ──────────────────────────────────────────────────────────────

    def get_active_models(self, tier: Optional[str] = None) -> list[ModelInfo]:
        with self._lock:
            models = []
            for d in self._data["models"].values():
                if d["status"] != "active":
                    continue
                if tier and d["tier"] != tier:
                    continue
                models.append(_dict_to_model(d))
            return models

    def get_all_models(self) -> list[ModelInfo]:
        with self._lock:
            return [_dict_to_model(d) for d in self._data["models"].values()]

    def upsert_model(self, model: ModelInfo) -> None:
        with self._lock:
            self._data["models"][model.model_id] = _model_to_dict(model)
            self._save()

    def retire_model(self, model_id: str) -> None:
        with self._lock:
            if model_id in self._data["models"]:
                self._data["models"][model_id]["status"] = "retired"
                self._save()

    def count_models(self) -> int:
        with self._lock:
            return len(self._data["models"])

    # ── Probe cache ───────────────────────────────────────────────────────────

    def get_probe(self, model_id: str) -> Optional[ProbeResult]:
        with self._lock:
            d = self._data["probes"].get(model_id)
            return _dict_to_probe(d) if d else None

    def get_all_probes(self) -> list[ProbeResult]:
        with self._lock:
            return [_dict_to_probe(d) for d in self._data["probes"].values()]

    def upsert_probe(self, probe: ProbeResult) -> None:
        with self._lock:
            self._data["probes"][probe.model_id] = _probe_to_dict(probe)
            self._save()

    # ── Call history ──────────────────────────────────────────────────────────

    def record_call(self, record: CallRecord) -> None:
        with self._lock:
            self._data["history"].append(_call_to_dict(record))
            self._save()

    def get_history(self, model_id: str, since: datetime) -> list[CallRecord]:
        with self._lock:
            results = []
            for d in self._data["history"]:
                if d["model_id"] != model_id:
                    continue
                called_at = _str_to_dt(d.get("called_at"))
                if called_at and called_at >= since:
                    results.append(_dict_to_call(d))
            return results

    def get_all_history(self, since: datetime) -> list[CallRecord]:
        with self._lock:
            results = []
            for d in self._data["history"]:
                called_at = _str_to_dt(d.get("called_at"))
                if called_at and called_at >= since:
                    results.append(_dict_to_call(d))
            return results

    def prune_old_records(self, before: datetime) -> int:
        with self._lock:
            original_count = len(self._data["history"])
            self._data["history"] = [
                d for d in self._data["history"]
                if _str_to_dt(d.get("called_at")) and _str_to_dt(d["called_at"]) >= before
            ]
            pruned = original_count - len(self._data["history"])
            if pruned > 0:
                self._save()
            return pruned

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status_summary(self) -> dict:
        with self._lock:
            models = self._data["models"]
            active = [m for m in models.values() if m["status"] == "active"]
            return {
                "total_models": len(models),
                "active_free": sum(1 for m in active if m["tier"] == "free"),
                "active_cheap": sum(1 for m in active if m["tier"] == "cheap"),
                "active_paid": sum(1 for m in active if m["tier"] == "paid"),
                "active_local": sum(1 for m in active if m["tier"] == "local"),
                "total_probes": len(self._data["probes"]),
                "total_history": len(self._data["history"]),
            }
