"""Storage backend protocol — all backends implement this interface."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult


@runtime_checkable
class StorageBackend(Protocol):
    """Interface for all storage backends (SQLite, MySQL, JSON).

    Every backend must implement all methods in this protocol.
    The interface is intentionally synchronous — storage operations
    are fast (local disk or DB) and the async layer lives in the
    selector and client modules.
    """

    # ── Registry ──────────────────────────────────────────────────────────────

    def get_active_models(self, tier: Optional[str] = None) -> list[ModelInfo]:
        """Get all models with status='active', optionally filtered by tier."""
        ...

    def get_all_models(self) -> list[ModelInfo]:
        """Get all models regardless of status."""
        ...

    def upsert_model(self, model: ModelInfo) -> None:
        """Insert or update a model in the registry."""
        ...

    def retire_model(self, model_id: str) -> None:
        """Set a model's status to 'retired'."""
        ...

    def count_models(self) -> int:
        """Count total models in the registry."""
        ...

    # ── Probe cache ───────────────────────────────────────────────────────────

    def get_probe(self, model_id: str) -> Optional[ProbeResult]:
        """Get the most recent probe result for a model."""
        ...

    def get_all_probes(self) -> list[ProbeResult]:
        """Get all probe cache entries."""
        ...

    def upsert_probe(self, probe: ProbeResult) -> None:
        """Insert or update a probe result."""
        ...

    # ── Call history ──────────────────────────────────────────────────────────

    def record_call(self, record: CallRecord) -> None:
        """Record a completed LLM call."""
        ...

    def get_history(self, model_id: str, since: datetime) -> list[CallRecord]:
        """Get call history for a specific model since a given time."""
        ...

    def get_all_history(self, since: datetime) -> list[CallRecord]:
        """Get all call history since a given time."""
        ...

    def prune_old_records(self, before: datetime) -> int:
        """Delete call records older than the given time. Returns count deleted."""
        ...

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status_summary(self) -> dict:
        """Return a summary of the storage state for health/status queries."""
        ...

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Set up storage (create tables/files). Idempotent."""
        ...

    def close(self) -> None:
        """Release resources (close connections/files)."""
        ...
