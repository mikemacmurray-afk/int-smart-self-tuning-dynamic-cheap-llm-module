"""Model selector — ranking engine and probe management.

The brain of Smart LLM. Handles:
- Seed model bootstrap
- Model ranking (composite score = probe * 0.6 + history * 0.4)
- Dynamic timeout selection
- Probe scheduling decisions
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult
from smart_llm.storage.base import StorageBackend

logger = logging.getLogger("smart_llm")

# ── Seed models — bootstrap on first run ──────────────────────────────────────
# Verified against OpenRouter catalogue 2026-03-31.
# These ensure the system works immediately without waiting for a catalogue scan.

SEED_MODELS = [
    # Free — tried first (zero cost)
    {"model_id": "google/gemma-3-12b-it:free",              "tier": "free",  "provider": "google"},
    {"model_id": "google/gemma-3-27b-it:free",              "tier": "free",  "provider": "google"},
    {"model_id": "meta-llama/llama-3.3-70b-instruct:free",  "tier": "free",  "provider": "meta"},
    {"model_id": "qwen/qwen3-next-80b-a3b-instruct:free",   "tier": "free",  "provider": "alibaba"},
    {"model_id": "meta-llama/llama-3.2-3b-instruct:free",   "tier": "free",  "provider": "meta"},
    # Cheap paid — tried before expensive fallbacks
    {"model_id": "google/gemini-2.5-flash-lite",            "tier": "cheap", "provider": "google"},
    {"model_id": "google/gemini-2.5-flash",                 "tier": "cheap", "provider": "google"},
    {"model_id": "mistralai/mistral-small-3.1-24b-instruct","tier": "cheap", "provider": "mistral"},
    # Paid — absolute last resort
    {"model_id": "google/gemma-3-27b-it",                   "tier": "paid",  "provider": "google"},
]

# ── Scoring constants ─────────────────────────────────────────────────────────

PROBE_WEIGHT = 0.6
HISTORY_WEIGHT = 0.4
HISTORY_DAYS = 7               # Rolling window for history scoring
HISTORY_HOUR_WINDOW = 2        # ±hours for day-of-week pattern matching
PROBE_CACHE_TTL_MINUTES = 15   # How long probes are considered fresh
RE_PROBE_INTERVAL_MINUTES = 45 # Re-probe failed models after this


class ModelSelector:
    """Model ranking engine.

    Combines live probe results with historical call patterns
    to produce a dynamically-ranked list of models.

    Usage:
        selector = ModelSelector(storage=sqlite_backend)
        selector.seed_registry()  # First run only (idempotent)
        ranked = selector.get_ranked_models()      # [(model_id, score), ...]
        ordered, timeout = selector.get_ordered_models()  # Full priority chain
    """

    def __init__(
        self,
        storage: StorageBackend,
        probe_cache_ttl_minutes: int = PROBE_CACHE_TTL_MINUTES,
        history_hour_window: int = HISTORY_HOUR_WINDOW,
    ):
        self._storage = storage
        self._probe_ttl = probe_cache_ttl_minutes
        self._history_window = history_hour_window

    def seed_registry(self) -> None:
        """Populate the registry with seed models on first run. Idempotent."""
        if self._storage.count_models() > 0:
            return

        now = datetime.now()
        for m in SEED_MODELS:
            self._storage.upsert_model(ModelInfo(
                model_id=m["model_id"],
                tier=m["tier"],
                provider=m["provider"],
                status="active",
                added_at=now,
                last_scanned_at=now,
            ))
        logger.info(f"[Selector] Seeded registry with {len(SEED_MODELS)} models")

    def get_ranked_models(self) -> list[tuple[str, float]]:
        """Rank active free models by composite score.

        Returns list of (model_id, score) sorted highest-first.
        Score = probe_score * 0.6 + history_score * 0.4
        """
        free_models = self._storage.get_active_models(tier="free")
        if not free_models:
            # Fallback to seed models if registry is empty
            free_models = [
                ModelInfo(model_id=m["model_id"], tier="free", provider=m["provider"], status="active")
                for m in SEED_MODELS if m["tier"] == "free"
            ]

        now = datetime.now()
        scored = []
        for model in free_models:
            ps = self._probe_score(model.model_id, now)
            hs = self._history_score(model.model_id, now)
            final = ps * PROBE_WEIGHT + hs * HISTORY_WEIGHT
            scored.append((model.model_id, final))
            logger.debug(
                f"[Selector] {model.model_id}: probe={ps:.2f} hist={hs:.2f} final={final:.2f}"
            )

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_ordered_models(self) -> tuple[list[str], int]:
        """Get the full priority-ordered model list and dynamic timeout.

        Returns:
            (ordered_model_list, per_attempt_timeout_seconds)

        Order: ranked free models → cheap models → paid models
        Timeout: 12s (aggressive) / 25s (moderate) / 35s (conservative)
        """
        # Rank free models
        ranked_free = self.get_ranked_models()

        # Get cheap and paid models
        cheap_models = [m.model_id for m in self._storage.get_active_models(tier="cheap")]
        paid_models = [m.model_id for m in self._storage.get_active_models(tier="paid")]

        # Fallback if no cheap/paid in registry
        if not cheap_models:
            cheap_models = [m["model_id"] for m in SEED_MODELS if m["tier"] == "cheap"]
        if not paid_models:
            paid_models = [m["model_id"] for m in SEED_MODELS if m["tier"] == "paid"]

        # Build ordered list
        ordered = [m for m, _ in ranked_free] + cheap_models + paid_models

        # Dynamic timeout based on best probe
        timeout = self._calculate_timeout(ranked_free)

        logger.info(
            f"[Selector] Order: {[m for m, _ in ranked_free[:3]]}... "
            f"timeout={timeout}s"
        )
        return ordered, timeout

    def get_models_to_probe(self) -> list[str]:
        """Determine which active models need probing (stale or failed cache).

        Returns list of model_ids that should be probed.
        """
        now = datetime.now()
        stale_cutoff = now - timedelta(minutes=self._probe_ttl)
        re_probe_cutoff = now - timedelta(minutes=RE_PROBE_INTERVAL_MINUTES)

        free_models = self._storage.get_active_models(tier="free")
        to_probe = []

        for model in free_models:
            probe = self._storage.get_probe(model.model_id)
            if probe is None:
                to_probe.append(model.model_id)
            elif probe.probed_at < stale_cutoff:
                to_probe.append(model.model_id)
            elif probe.status != "ok" and probe.probed_at < re_probe_cutoff:
                to_probe.append(model.model_id)

        return to_probe

    def record_call(
        self,
        model_id: str,
        response_ms: Optional[int],
        status: str,
        token_count: Optional[int] = None,
    ) -> None:
        """Record a completed LLM call in history.

        Also prunes old records probabilistically (1-in-20 calls).
        """
        record = CallRecord(
            model_id=model_id,
            response_ms=response_ms,
            status=status,
            token_count=token_count,
        )
        self._storage.record_call(record)

        # Probabilistic pruning
        import random
        if random.randint(1, 20) == 1:
            cutoff = datetime.now() - timedelta(days=HISTORY_DAYS)
            pruned = self._storage.prune_old_records(before=cutoff)
            if pruned > 0:
                logger.info(f"[Selector] Pruned {pruned} old call records")

    # ── Private scoring methods ───────────────────────────────────────────────

    def _probe_score(self, model_id: str, now: datetime) -> float:
        """Score a model based on its most recent probe result.

        Returns:
            1.0  — ok + fast (< 3s)
            0.7  — ok + slow (3-8s)
            0.5  — no data / stale
            0.1  — rate limited (429)
            0.05 — timeout / error
        """
        probe = self._storage.get_probe(model_id)
        if not probe:
            return 0.5  # No data — neutral

        stale_cutoff = now - timedelta(minutes=self._probe_ttl)
        if probe.probed_at < stale_cutoff:
            return 0.5  # Stale — neutral

        if probe.status == "ok":
            if probe.response_ms is not None and probe.response_ms < 3000:
                return 1.0  # Fast
            return 0.7  # Slow but working

        if probe.status == "rate_limited":
            return 0.1

        return 0.05  # timeout or error

    def _history_score(self, model_id: str, now: datetime) -> float:
        """Score a model based on historical success rate.

        Looks at calls from the same day-of-week and ±HISTORY_HOUR_WINDOW
        hours over the last HISTORY_DAYS days.

        Returns success_rate (0.0 to 1.0), or 0.5 if no data.
        """
        cutoff = now - timedelta(days=HISTORY_DAYS)
        history = self._storage.get_history(model_id, since=cutoff)

        if not history:
            return 0.5  # No data — neutral

        dow = now.weekday()
        hour = now.hour
        hour_min = (hour - self._history_window) % 24
        hour_max = (hour + self._history_window) % 24

        # Filter by same day-of-week and similar hour
        filtered = [r for r in history if r.day_of_week == dow]
        if hour_min <= hour_max:
            filtered = [r for r in filtered if hour_min <= r.hour_of_day <= hour_max]
        else:
            # Wraps midnight
            filtered = [r for r in filtered if r.hour_of_day >= hour_min or r.hour_of_day <= hour_max]

        if not filtered:
            return 0.5  # No relevant data

        successes = sum(1 for r in filtered if r.status == "ok")
        return successes / len(filtered)

    def _calculate_timeout(self, ranked_free: list[tuple[str, float]]) -> int:
        """Calculate dynamic timeout based on best working probe.

        Returns:
            12  — best probe < 3s (aggressive)
            25  — best probe 3-8s (moderate)
            35  — no working probes (conservative)
        """
        now = datetime.now()
        stale_cutoff = now - timedelta(minutes=self._probe_ttl)
        best_ms = None

        for model_id, _ in ranked_free:
            probe = self._storage.get_probe(model_id)
            if (probe and probe.status == "ok" and
                    probe.response_ms is not None and
                    probe.probed_at >= stale_cutoff):
                if best_ms is None or probe.response_ms < best_ms:
                    best_ms = probe.response_ms

        if best_ms is not None and best_ms < 3000:
            return 12
        elif best_ms is not None:
            return 25
        else:
            return 35
