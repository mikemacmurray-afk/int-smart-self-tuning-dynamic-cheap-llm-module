"""Local model provider for Ollama, LM Studio, and vLLM.

Uses the OpenAI-compatible API that these local servers expose.
Priority: if configured and responding, local models always win (zero cost).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

import httpx
from openai import AsyncOpenAI

from smart_llm.data_models import ModelInfo, ProbeResult, ProviderResponse

logger = logging.getLogger("smart_llm")

PROBE_PAYLOAD = "Reply with exactly: ok"
PROBE_MAX_TOKENS = 5
PROBE_TIMEOUT_S = 8.0


class LocalProvider:
    """Local model provider (Ollama, LM Studio, vLLM).

    Connects to a locally-running model server via its OpenAI-compatible API.
    If configured and responding, local models always take priority (zero cost).

    Args:
        base_url: Base URL of the local server (e.g. "http://localhost:11434")
        model: Preferred model name (e.g. "qwen2.5:7b")
    """

    name = "local"

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self._base_url = base_url
        self._model = model
        self._client: Optional[AsyncOpenAI] = None
        if base_url:
            # Ollama and LM Studio both expose OpenAI-compatible /v1 endpoints
            api_base = base_url.rstrip("/")
            if not api_base.endswith("/v1"):
                api_base += "/v1"
            self._client = AsyncOpenAI(
                base_url=api_base,
                api_key="not-needed",  # Local servers don't require auth
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
        """Make an LLM call to the local model server."""
        if not self._client:
            raise RuntimeError("Local provider not configured — no base_url")

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

        return ProviderResponse(
            content=content,
            model_id=model_id,
            response_ms=elapsed_ms,
            token_count=token_count,
            raw_response=response,
        )

    async def probe(self, model_id: str) -> ProbeResult:
        """Send a tiny probe to the local model."""
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
        except Exception:
            ms = int((asyncio.get_event_loop().time() - start) * 1000)
            return ProbeResult(model_id=model_id, response_ms=None, status="error")

    async def list_available_models(self) -> list[ModelInfo]:
        """Discover models available on the local server.

        Tries Ollama's /api/tags endpoint first, then falls back to
        OpenAI-compatible /v1/models endpoint.
        """
        if not self._base_url:
            return []

        now = datetime.now()
        models = []

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try Ollama's native API first
                try:
                    resp = await client.get(f"{self._base_url.rstrip('/')}/api/tags")
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            model_name = m.get("name", m.get("model", ""))
                            if model_name:
                                models.append(ModelInfo(
                                    model_id=model_name,
                                    tier="local",
                                    provider="ollama",
                                    status="active",
                                    added_at=now,
                                    last_scanned_at=now,
                                ))
                        if models:
                            return models
                except Exception:
                    pass

                # Fallback: OpenAI-compatible /v1/models
                try:
                    api_base = self._base_url.rstrip("/")
                    if not api_base.endswith("/v1"):
                        api_base += "/v1"
                    resp = await client.get(f"{api_base}/models")
                    if resp.status_code == 200:
                        for m in resp.json().get("data", []):
                            model_id = m.get("id", "")
                            if model_id:
                                models.append(ModelInfo(
                                    model_id=model_id,
                                    tier="local",
                                    provider="local",
                                    status="active",
                                    added_at=now,
                                    last_scanned_at=now,
                                ))
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"[Local] Failed to discover models: {e}")

        return models

    async def is_available(self) -> bool:
        """Check if the local model server is running and responding."""
        if not self._base_url:
            return False

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Try Ollama health endpoint
                try:
                    resp = await client.get(f"{self._base_url.rstrip('/')}/api/tags")
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass

                # Try OpenAI-compatible endpoint
                try:
                    api_base = self._base_url.rstrip("/")
                    if not api_base.endswith("/v1"):
                        api_base += "/v1"
                    resp = await client.get(f"{api_base}/models")
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass

        except Exception:
            pass

        return False
