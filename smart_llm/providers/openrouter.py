"""OpenRouter LLM provider implementation.

Uses the OpenAI SDK pointed at OpenRouter's API. Handles:
- LLM calls with timeout and error classification
- Health probes (tiny "Reply with exactly: ok" prompt)
- Catalogue discovery via /api/v1/models endpoint
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from openai import AsyncOpenAI

from smart_llm.data_models import ModelInfo, ProbeResult, ProviderResponse

logger = logging.getLogger("smart_llm")

# Probe constants
PROBE_PAYLOAD = "Reply with exactly: ok"
PROBE_MAX_TOKENS = 5
PROBE_TIMEOUT_S = 8.0
QUALITY_PROBE_PROMPT = 'Respond with only this JSON object, nothing else: {"ok": true}'


class OpenRouterProvider:
    """OpenRouter LLM provider.

    Wraps the OpenAI SDK pointed at https://openrouter.ai/api/v1.
    Handles free, cheap, and paid model tiers.
    """

    name = "openrouter"

    def __init__(self, api_key: str | None = None, cheap_price_threshold: float = 0.001):
        self._api_key = api_key
        self._cheap_threshold = cheap_price_threshold
        self._client: Optional[AsyncOpenAI] = None
        if api_key:
            self._client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                max_retries=0,
            )

    async def call(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        """Make an LLM call via OpenRouter."""
        if not self._client:
            raise RuntimeError("OpenRouter provider not configured — no API key")

        start = asyncio.get_event_loop().time()
        response = await self._client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        elapsed_ms = int((asyncio.get_event_loop().time() - start) * 1000)

        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content

        token_count = None
        if hasattr(response, "usage") and response.usage:
            token_count = response.usage.total_tokens

        model_used = response.model if hasattr(response, "model") else model_id

        return ProviderResponse(
            content=content,
            model_id=model_used,
            response_ms=elapsed_ms,
            token_count=token_count,
            raw_response=response,
        )

    async def probe(self, model_id: str) -> ProbeResult:
        """Send a tiny probe to one model. Returns ProbeResult with status and timing."""
        if not self._client:
            return ProbeResult(model_id=model_id, status="error")

        start = asyncio.get_event_loop().time()
        try:
            await self._client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": PROBE_PAYLOAD}],
                max_tokens=PROBE_MAX_TOKENS,
                timeout=PROBE_TIMEOUT_S,
            )
            ms = int((asyncio.get_event_loop().time() - start) * 1000)
            return ProbeResult(model_id=model_id, response_ms=ms, status="ok")
        except Exception as e:
            ms = int((asyncio.get_event_loop().time() - start) * 1000)
            err = str(e).lower()
            if "429" in err or "rate" in err:
                return ProbeResult(model_id=model_id, response_ms=None, status="rate_limited")
            if "timeout" in err or "timed out" in err:
                return ProbeResult(model_id=model_id, response_ms=None, status="timeout")
            return ProbeResult(model_id=model_id, response_ms=None, status="error")

    async def quality_probe(self, model_id: str) -> tuple[bool, Optional[int]]:
        """Quality check: can the model respond AND return parseable JSON with 'ok' key?

        Used during catalogue scan to validate new candidates.
        Returns (passed, response_ms).
        """
        if not self._client:
            return False, None

        start = asyncio.get_event_loop().time()
        try:
            resp = await self._client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": QUALITY_PROBE_PROMPT}],
                max_tokens=20,
                timeout=PROBE_TIMEOUT_S,
            )
            ms = int((asyncio.get_event_loop().time() - start) * 1000)
            content = (resp.choices[0].message.content or "") if resp.choices else ""
            match = re.search(r'\{.*?\}', content, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return "ok" in parsed, ms
            return False, ms
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            ms = int((asyncio.get_event_loop().time() - start) * 1000)
            return False, ms

    async def list_available_models(self) -> list[ModelInfo]:
        """Fetch the OpenRouter model catalogue and return free/cheap models."""
        if not self._api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                resp.raise_for_status()
                catalogue = resp.json().get("data", [])
        except Exception as e:
            logger.warning(f"[OpenRouter] Catalogue fetch failed: {e}")
            return []

        models = []
        now = datetime.now()
        for m in catalogue:
            tier = self._classify_tier(m)
            if tier is None:
                continue  # Not free or cheap — skip
            provider_name = m["id"].split("/")[0]
            models.append(ModelInfo(
                model_id=m["id"],
                tier=tier,
                provider=provider_name,
                status="candidate",
                added_at=now,
                last_scanned_at=now,
            ))
        return models

    def _classify_tier(self, model_dict: dict) -> Optional[str]:
        """Classify a model as free, cheap, or None (too expensive)."""
        model_id = model_dict.get("id", "")
        if model_id.endswith(":free"):
            return "free"
        try:
            price = float(model_dict.get("pricing", {}).get("prompt", 999))
            if price <= self._cheap_threshold:
                return "cheap"
        except (ValueError, TypeError):
            pass
        return None

    async def is_available(self) -> bool:
        """Check if OpenRouter is configured (has API key)."""
        return self._api_key is not None and len(self._api_key) > 0
