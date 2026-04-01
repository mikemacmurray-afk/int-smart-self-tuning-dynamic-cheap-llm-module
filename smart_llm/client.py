"""SmartLLM — the main client interface.

This is the primary class that users interact with. It ties together
the storage backend, providers, selector, and registry into a single
clean API.

Usage:
    from smart_llm import SmartLLM

    llm = SmartLLM(api_key="sk-or-...")
    result = await llm.ask("Summarize this text: ...")
    data = await llm.ask_json("Extract the name and date: ...")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from smart_llm.config import SmartLLMConfig
from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult, ProviderResponse
from smart_llm.logger import setup_logger
from smart_llm.providers.local import LocalProvider
from smart_llm.providers.openrouter import OpenRouterProvider
from smart_llm.registry import RegistryManager
from smart_llm.selector import ModelSelector
from smart_llm.storage import create_storage
from smart_llm.storage.base import StorageBackend

logger = logging.getLogger("smart_llm")


class SmartLLM:
    """Self-tuning LLM client for free/cheap models.

    Automatically selects the best available model, handles fallback
    through ranked alternatives, records call history, and runs
    background health probes.

    Priority chain: Local model → Free OpenRouter → Cheap → Paid (last resort)

    Args:
        api_key: OpenRouter API key (or reads SMART_LLM_API_KEY env var)
        storage: Storage backend — "sqlite" | "mysql" | "json"
        storage_path: File path for sqlite/json backends
        storage_url: Connection URL for mysql backend
        local_url: URL for local model server (e.g. "http://localhost:11434")
        local_model: Preferred local model name
        log_retention_days: Rolling log window (default 7)
        probe_interval_minutes: Health check frequency (default 15)
        scan_interval_days: Catalogue scan frequency (default 30)
    """

    def __init__(
        self,
        api_key: str | None = None,
        storage: str = "sqlite",
        storage_path: str | None = None,
        storage_url: str | None = None,
        local_url: str | None = None,
        local_model: str | None = None,
        log_retention_days: int = 7,
        probe_interval_minutes: int = 15,
        scan_interval_days: int = 30,
    ):
        # Build config (constructor args override env vars)
        env_config = SmartLLMConfig.from_env()
        self._config = SmartLLMConfig(
            api_key=api_key or env_config.api_key,
            storage=storage or env_config.storage,
            storage_path=storage_path or env_config.storage_path,
            storage_url=storage_url or env_config.storage_url,
            local_url=local_url or env_config.local_url,
            local_model=local_model or env_config.local_model,
            log_retention_days=log_retention_days,
            probe_interval_minutes=probe_interval_minutes,
            scan_interval_days=scan_interval_days,
        )

        # Setup logger
        setup_logger("smart_llm")

        # Initialize storage
        storage_kwargs = {}
        if self._config.storage == "mysql":
            storage_kwargs["url"] = self._config.storage_url
        elif self._config.storage in ("sqlite", "json"):
            if self._config.storage_path:
                storage_kwargs["path"] = self._config.storage_path

        self._storage: StorageBackend = create_storage(self._config.storage, **storage_kwargs)
        self._storage.initialize()

        # Initialize providers
        self._openrouter = OpenRouterProvider(
            api_key=self._config.api_key,
            cheap_price_threshold=self._config.cheap_price_threshold,
        )
        self._local = LocalProvider(
            base_url=self._config.local_url,
            model=self._config.local_model,
        )

        # Initialize selector and registry
        self._selector = ModelSelector(
            storage=self._storage,
            probe_cache_ttl_minutes=self._config.probe_cache_ttl_minutes,
            history_hour_window=self._config.history_hour_window,
        )
        self._registry = RegistryManager(
            storage=self._storage,
            api_key=self._config.api_key,
            scan_interval_days=self._config.scan_interval_days,
            emergency_threshold_hours=self._config.emergency_scan_threshold_hours,
            cheap_price_threshold=self._config.cheap_price_threshold,
        )

        # Seed the registry on first use
        self._selector.seed_registry()

        # Track last probe/scan times
        self._last_probe_time: Optional[datetime] = None
        self._last_scan_time: Optional[datetime] = None

        logger.info(
            f"[SmartLLM] Initialized — storage={self._config.storage}, "
            f"api_key={'set' if self._config.api_key else 'not set'}, "
            f"local={'configured' if self._config.local_url else 'not configured'}"
        )

    # ── Core API ──────────────────────────────────────────────────────────────

    async def ask(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt, get a text response.

        Automatically selects the best model, handles fallback, and records history.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum response tokens (default 1024)
            temperature: Sampling temperature (default 0.3)

        Returns:
            The response text content.

        Raises:
            RuntimeError: If all models fail.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._call_with_fallback(messages, max_tokens, temperature)
        return response.content

    async def ask_json(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        """Send a prompt, get parsed JSON back.

        Extracts JSON from the response, handling markdown code fences
        and embedded JSON objects.

        Args:
            prompt: The user prompt (should ask for JSON output)
            system: Optional system prompt (recommend including "Return JSON" instructions)
            max_tokens: Maximum response tokens (default 1024)

        Returns:
            Parsed JSON dict.

        Raises:
            RuntimeError: If all models fail.
            ValueError: If response cannot be parsed as JSON.
        """
        if system is None:
            system = "You must respond with valid JSON only. No explanation, no markdown."

        result = await self.ask(prompt, system=system, max_tokens=max_tokens, temperature=0.1)
        return self._extract_json(result)

    # ── Operational API ───────────────────────────────────────────────────────

    async def probe_all(self) -> list[ProbeResult]:
        """Manually trigger a probe of all active models.

        Returns list of ProbeResult for each probed model.
        """
        return await self._run_probes(force=True)

    async def scan_catalogue(self) -> dict:
        """Manually trigger a catalogue scan.

        Returns summary dict with discovery/retirement counts.
        """
        return await self._registry.scan_catalogue()

    def status(self) -> dict:
        """Get current health and status summary.

        Returns dict with health, active model counts, top model, last probe/scan times.
        """
        storage_status = self._storage.get_status_summary()
        ranked = self._selector.get_ranked_models()

        health = "ok"
        if storage_status.get("active_free", 0) == 0:
            health = "degraded"
        elif self._registry.is_scan_overdue():
            health = "stale_catalogue"

        return {
            "health": health,
            "active_free": storage_status.get("active_free", 0),
            "active_cheap": storage_status.get("active_cheap", 0),
            "active_paid": storage_status.get("active_paid", 0),
            "active_local": storage_status.get("active_local", 0),
            "total_models": storage_status.get("total_models", 0),
            "top_model": ranked[0][0] if ranked else None,
            "top_score": round(ranked[0][1], 3) if ranked else None,
            "last_probe": self._last_probe_time.isoformat() if self._last_probe_time else None,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "total_history": storage_status.get("total_history", 0),
        }

    def get_logs(self, hours: int = 24) -> list[CallRecord]:
        """Get recent call history for manual review.

        Args:
            hours: How far back to look (default 24 hours)

        Returns:
            List of CallRecord objects, most recent first.
        """
        since = datetime.now() - timedelta(hours=hours)
        return self._storage.get_all_history(since=since)

    def get_ranked_models(self) -> list[tuple[str, float]]:
        """Get current model ranking with scores. For inspection/debugging."""
        return self._selector.get_ranked_models()

    # ── Internal methods ──────────────────────────────────────────────────────

    async def _call_with_fallback(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> ProviderResponse:
        """Walk the ranked model list with automatic fallback.

        Priority: local model → ranked free → cheap → paid

        Records call result in history for future ranking.
        """
        # Maybe run probes if stale
        await self._maybe_run_probes()

        # Try local model first (if configured)
        if self._config.local_url:
            try:
                if await self._local.is_available():
                    local_models = await self._local.list_available_models()
                    model_to_try = self._config.local_model
                    if not model_to_try and local_models:
                        model_to_try = local_models[0].model_id
                    if model_to_try:
                        try:
                            response = await self._local.call(
                                model_id=model_to_try,
                                messages=messages,
                                max_tokens=max_tokens,
                                temperature=temperature,
                                timeout=30.0,
                            )
                            if response.content.strip():
                                self._selector.record_call(
                                    model_id=model_to_try,
                                    response_ms=response.response_ms,
                                    status="ok",
                                    token_count=response.token_count,
                                )
                                logger.info(
                                    f"[SmartLLM] Local model {model_to_try}: "
                                    f"ok {response.response_ms}ms"
                                )
                                return response
                        except Exception as e:
                            logger.warning(f"[SmartLLM] Local model failed: {e}")
            except Exception as e:
                logger.debug(f"[SmartLLM] Local provider check failed: {e}")

        # Fall through to OpenRouter models
        ordered, timeout = self._selector.get_ordered_models()

        if not ordered:
            raise RuntimeError(
                "No models available. Check your SMART_LLM_API_KEY or configure a local model."
            )

        last_error = ""
        for i, model_id in enumerate(ordered):
            try:
                logger.info(f"[SmartLLM] Attempt {i+1}/{len(ordered)}: {model_id}")
                response = await self._openrouter.call(
                    model_id=model_id,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=float(timeout),
                )

                if not response.content.strip():
                    last_error = f"Empty response from {model_id}"
                    logger.warning(f"[SmartLLM] {last_error}")
                    continue

                # Success — record and return
                self._selector.record_call(
                    model_id=model_id,
                    response_ms=response.response_ms,
                    status="ok",
                    token_count=response.token_count,
                )
                logger.info(
                    f"[SmartLLM] Success: {model_id} in {response.response_ms}ms"
                )
                return response

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"[SmartLLM] Attempt {i+1}/{len(ordered)} failed ({model_id}): {last_error}"
                )
                # Record the failure
                err_str = str(e).lower()
                status = "error"
                if "429" in err_str or "rate" in err_str:
                    status = "rate_limited"
                elif "timeout" in err_str or "timed out" in err_str:
                    status = "timeout"

                self._selector.record_call(
                    model_id=model_id,
                    response_ms=None,
                    status=status,
                )

                if i < len(ordered) - 1:
                    await asyncio.sleep(1)  # Brief pause before retry

        raise RuntimeError(
            f"All {len(ordered)} models failed. Last error: {last_error}"
        )

    async def _maybe_run_probes(self) -> None:
        """Run probes if cache is stale."""
        now = datetime.now()
        if (self._last_probe_time and
                now - self._last_probe_time < timedelta(minutes=self._config.probe_interval_minutes)):
            return  # Still fresh

        to_probe = self._selector.get_models_to_probe()
        if not to_probe:
            return

        # Run probes in background (non-blocking)
        asyncio.create_task(self._run_probes_background(to_probe))

    async def _run_probes_background(self, model_ids: list[str]) -> None:
        """Run probes in the background without blocking the main call."""
        try:
            await self._run_probes_for(model_ids)
        except Exception as e:
            logger.warning(f"[SmartLLM] Background probe failed: {e}")

    async def _run_probes(self, force: bool = False) -> list[ProbeResult]:
        """Run probes for models that need it."""
        if force:
            free_models = self._storage.get_active_models(tier="free")
            model_ids = [m.model_id for m in free_models]
        else:
            model_ids = self._selector.get_models_to_probe()

        if not model_ids:
            return []

        return await self._run_probes_for(model_ids)

    async def _run_probes_for(self, model_ids: list[str]) -> list[ProbeResult]:
        """Probe specific models and update cache."""
        logger.info(f"[SmartLLM] Probing {len(model_ids)} models...")
        results = await asyncio.gather(
            *[self._openrouter.probe(m) for m in model_ids]
        )

        now = datetime.now()
        for result in results:
            self._storage.upsert_probe(result)
            # Update registry last_active_at for healthy models
            if result.status == "ok":
                models = self._storage.get_active_models()
                for m in models:
                    if m.model_id == result.model_id:
                        m.last_active_at = now
                        self._storage.upsert_model(m)
                        break
            logger.info(
                f"[SmartLLM] Probe {result.model_id}: "
                f"{result.status} {result.response_ms}ms"
            )

        self._last_probe_time = now

        # Check if catalogue scan is needed
        await self._maybe_scan_catalogue()

        return results

    async def _maybe_scan_catalogue(self) -> None:
        """Run catalogue scan if overdue or emergency."""
        if self._registry.is_scan_overdue():
            logger.info("[SmartLLM] Catalogue scan triggered")
            summary = await self._registry.scan_catalogue()
            self._last_scan_time = datetime.now()
            logger.info(f"[SmartLLM] Catalogue scan result: {summary}")

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from a response that may contain markdown fences or extra text."""
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences
        fenced = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Find first JSON object
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {text[:200]}...")

    def __del__(self):
        """Clean up storage on garbage collection."""
        try:
            if hasattr(self, '_storage') and self._storage:
                self._storage.close()
        except Exception:
            pass
