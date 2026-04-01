"""Registry manager — catalogue scanning, discovery, and retirement.

The slow layer of model management. Runs monthly (or on emergency)
to discover new free/cheap models and retire removed ones.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from smart_llm.data_models import ModelInfo
from smart_llm.providers.openrouter import OpenRouterProvider
from smart_llm.storage.base import StorageBackend

logger = logging.getLogger("smart_llm")

# Constants
CATALOGUE_SCAN_INTERVAL_DAYS = 30
EMERGENCY_SCAN_THRESHOLD_HOURS = 2
CHEAP_PRICE_THRESHOLD = 0.001


class RegistryManager:
    """Manages the model catalogue — discovery, validation, retirement.

    Two triggers:
    1. Monthly scan: discovers new free/cheap models, retires removed ones
    2. Emergency scan: all free models failing → immediate rescan

    Usage:
        registry = RegistryManager(storage=backend, api_key="sk-or-...")
        if registry.is_scan_overdue():
            summary = await registry.scan_catalogue()
    """

    def __init__(
        self,
        storage: StorageBackend,
        api_key: str | None = None,
        scan_interval_days: int = CATALOGUE_SCAN_INTERVAL_DAYS,
        emergency_threshold_hours: int = EMERGENCY_SCAN_THRESHOLD_HOURS,
        cheap_price_threshold: float = CHEAP_PRICE_THRESHOLD,
    ):
        self._storage = storage
        self._api_key = api_key
        self._scan_interval = scan_interval_days
        self._emergency_threshold = emergency_threshold_hours
        self._cheap_threshold = cheap_price_threshold
        self._provider = OpenRouterProvider(
            api_key=api_key,
            cheap_price_threshold=cheap_price_threshold,
        )

    def is_scan_overdue(self) -> bool:
        """Check if a catalogue scan should run now.

        Returns True if:
        - No scan has ever run (registry was just seeded), OR
        - Last scan was > scan_interval_days ago, OR
        - All active free models have had no successful probe in > emergency_threshold hours
        """
        # Monthly check
        models = self._storage.get_all_models()
        scanned = [m for m in models if m.last_scanned_at is not None]

        if not scanned:
            return True  # Never scanned

        latest_scan = max(m.last_scanned_at for m in scanned)
        monthly_cutoff = datetime.now() - timedelta(days=self._scan_interval)
        if latest_scan < monthly_cutoff:
            return True

        # Emergency check — all free active models failing
        emergency_cutoff = datetime.now() - timedelta(hours=self._emergency_threshold)
        active_free = self._storage.get_active_models(tier="free")
        if active_free and all(
            m.last_active_at is None or m.last_active_at < emergency_cutoff
            for m in active_free
        ):
            logger.warning(
                "[Registry] Emergency: all free models failing — triggering catalogue scan"
            )
            return True

        return False

    async def scan_catalogue(self) -> dict:
        """Run a full catalogue scan: discover, retire, validate.

        Returns a summary dict with counts of actions taken.
        """
        logger.info("[Registry] Scanning OpenRouter model catalogue...")

        # Fetch catalogue from OpenRouter
        catalogue_models = await self._fetch_catalogue()
        if catalogue_models is None:
            return {"error": "Catalogue fetch failed", "new_candidates": 0, "retired": 0, "promoted": 0}

        catalogue_ids = {m.model_id for m in catalogue_models}
        existing = {m.model_id: m for m in self._storage.get_all_models()}
        now = datetime.now()

        # ── Discover new models ───────────────────────────────────────────
        new_candidates = []
        for model in catalogue_models:
            if model.model_id not in existing:
                self._storage.upsert_model(model)
                new_candidates.append(model.model_id)
                logger.info(f"[Registry] New candidate: {model.model_id} ({model.tier})")
            else:
                # Update last_scanned_at for existing models
                ex = existing[model.model_id]
                ex.last_scanned_at = now
                self._storage.upsert_model(ex)

        # ── Retire models gone from catalogue ─────────────────────────────
        retired_count = 0
        for model_id, model in existing.items():
            if model_id not in catalogue_ids and model.status != "retired":
                # Only retire OpenRouter models, not local ones
                if model.provider != "ollama" and model.provider != "local":
                    self._storage.retire_model(model_id)
                    retired_count += 1
                    logger.info(f"[Registry] Retired (removed from catalogue): {model_id}")

        # ── Quality-validate new candidates ───────────────────────────────
        promoted = 0
        candidates = [
            m for m in self._storage.get_all_models() if m.status == "candidate"
        ]

        if candidates:
            logger.info(f"[Registry] Quality-validating {len(candidates)} candidates...")
            results = await asyncio.gather(
                *[self._quality_probe_one(c.model_id) for c in candidates]
            )

            for model, (passed, ms) in zip(candidates, results):
                if passed:
                    model.status = "active"
                    model.quality_score = 1.0
                    model.last_active_at = now
                    self._storage.upsert_model(model)
                    promoted += 1
                    logger.info(f"[Registry] Promoted to active: {model.model_id} ({ms}ms)")
                else:
                    model.quality_score = 0.0
                    self._storage.upsert_model(model)
                    logger.info(f"[Registry] Failed quality check: {model.model_id}")

        summary = {
            "new_candidates": len(new_candidates),
            "retired": retired_count,
            "promoted": promoted,
            "validated": len(candidates),
        }
        logger.info(f"[Registry] Catalogue scan complete: {summary}")
        return summary

    async def _fetch_catalogue(self) -> list[ModelInfo] | None:
        """Fetch the OpenRouter model catalogue."""
        try:
            return await self._provider.list_available_models()
        except Exception as e:
            logger.warning(f"[Registry] Catalogue fetch failed: {e}")
            return None

    async def _quality_probe_one(self, model_id: str) -> tuple[bool, Optional[int]]:
        """Quality-validate a single model candidate."""
        return await self._provider.quality_probe(model_id)

    def _classify_tier(self, model_dict: dict) -> Optional[str]:
        """Classify a model dict as free, cheap, or None."""
        return self._provider._classify_tier(model_dict)
