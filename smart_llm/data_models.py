"""Data models for Smart LLM — pure dataclasses, no ORM dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

VALID_TIERS = {"local", "free", "cheap", "paid"}
VALID_STATUSES = {"candidate", "active", "retired"}
VALID_PROBE_STATUSES = {"ok", "timeout", "rate_limited", "error", "unknown"}


@dataclass
class ModelInfo:
    """A model in the registry.

    Attributes:
        model_id: Unique identifier, e.g. "google/gemma-3-12b-it:free"
        tier: Cost tier — "local" | "free" | "cheap" | "paid"
        provider: Source — "openrouter" | "ollama" | "lmstudio"
        status: Lifecycle state — "candidate" | "active" | "retired"
        quality_score: 0.0–1.0 from quality probe; None = untested
        last_scanned_at: Last time seen in catalogue scan
        last_active_at: Last time a real probe returned ok
        added_at: When this model was first added to the registry
    """
    model_id: str
    tier: str
    provider: str
    status: str = "candidate"
    quality_score: Optional[float] = None
    last_scanned_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    added_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if self.tier not in VALID_TIERS:
            raise ValueError(f"Invalid tier '{self.tier}'. Must be one of {VALID_TIERS}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'. Must be one of {VALID_STATUSES}")


@dataclass
class ProbeResult:
    """Result of a single health probe against a model.

    Attributes:
        model_id: The model that was probed
        response_ms: Response time in milliseconds; None = failed/timed out
        status: "ok" | "timeout" | "rate_limited" | "error" | "unknown"
        probed_at: When the probe was executed
    """
    model_id: str
    response_ms: Optional[int] = None
    status: str = "unknown"
    probed_at: datetime = field(default_factory=datetime.now)


@dataclass
class CallRecord:
    """Record of a real LLM call, stored in rolling 7-day history.

    Attributes:
        model_id: The model that was called
        response_ms: Response time in milliseconds; None = failure
        status: "ok" | "timeout" | "rate_limited" | "error"
        called_at: When the call was made
        day_of_week: 0=Monday … 6=Sunday (auto-set from called_at)
        hour_of_day: 0-23 (auto-set from called_at)
        token_count: Tokens used, for cost tracking
    """
    model_id: str
    response_ms: Optional[int] = None
    status: str = "ok"
    called_at: datetime = field(default_factory=datetime.now)
    day_of_week: int = -1
    hour_of_day: int = -1
    token_count: Optional[int] = None

    def __post_init__(self):
        if self.day_of_week == -1:
            self.day_of_week = self.called_at.weekday()
        if self.hour_of_day == -1:
            self.hour_of_day = self.called_at.hour


@dataclass
class ProviderResponse:
    """Response from an LLM provider call.

    Attributes:
        content: The text content of the response
        model_id: The model that generated the response
        response_ms: Response time in milliseconds
        token_count: Tokens used (if available)
        raw_response: The raw response object from the provider SDK
    """
    content: str
    model_id: str
    response_ms: int
    token_count: Optional[int] = None
    raw_response: Optional[Any] = None
