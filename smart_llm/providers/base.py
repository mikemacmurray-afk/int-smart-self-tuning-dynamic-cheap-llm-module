"""LLM provider protocol — all providers implement this interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from smart_llm.data_models import ModelInfo, ProbeResult, ProviderResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for LLM providers (OpenRouter, Ollama, etc.).

    Each provider handles:
    - Making LLM calls (call)
    - Health probes (probe)
    - Model discovery (list_available_models)
    - Availability checks (is_available)
    """

    name: str

    async def call(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        """Make an LLM call. Returns ProviderResponse with content and timing."""
        ...

    async def probe(self, model_id: str) -> ProbeResult:
        """Send a tiny health probe to a model. Returns ProbeResult with status and timing."""
        ...

    async def list_available_models(self) -> list[ModelInfo]:
        """Discover available models from this provider."""
        ...

    async def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        ...
