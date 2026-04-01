"""Configuration for Smart LLM module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

VALID_STORAGE_BACKENDS = {"sqlite", "mysql", "json"}


@dataclass
class SmartLLMConfig:
    """All configuration for the SmartLLM module.

    Configuration is loaded in priority order:
    1. Constructor arguments (highest priority)
    2. Environment variables (via from_env())
    3. Defaults (lowest priority)

    Attributes:
        api_key: OpenRouter API key
        local_url: URL for local model server (Ollama/LM Studio)
        local_model: Preferred local model name
        storage: Storage backend — "sqlite" | "mysql" | "json"
        storage_path: File path for sqlite/json backends
        storage_url: Connection URL for mysql backend
        probe_interval_minutes: How often to health-check models (default 15)
        re_probe_interval_minutes: How long before retrying a failed model (default 45)
        scan_interval_days: How often to scan the OpenRouter catalogue (default 30)
        emergency_scan_threshold_hours: All free models failing triggers rescan (default 2)
        log_retention_days: How many days of call history to keep (default 7)
        cheap_price_threshold: Per 1K tokens — below this = "cheap" tier (default 0.001)
        probe_timeout_seconds: Max wait time for a health probe (default 8.0)
        probe_max_tokens: Max tokens for probe response (default 5)
        probe_cache_ttl_minutes: How long probe results are considered fresh (default 15)
        history_hour_window: ±hours for day-of-week pattern matching (default 2)
    """

    # API keys
    api_key: Optional[str] = None
    local_url: Optional[str] = None
    local_model: Optional[str] = None

    # Storage
    storage: str = "sqlite"
    storage_path: Optional[str] = None
    storage_url: Optional[str] = None

    # Tuning
    probe_interval_minutes: int = 15
    re_probe_interval_minutes: int = 45
    scan_interval_days: int = 30
    emergency_scan_threshold_hours: int = 2
    log_retention_days: int = 7
    cheap_price_threshold: float = 0.001

    # Probe settings
    probe_timeout_seconds: float = 8.0
    probe_max_tokens: int = 5
    probe_cache_ttl_minutes: int = 15

    # History
    history_hour_window: int = 2

    def __post_init__(self):
        if self.storage not in VALID_STORAGE_BACKENDS:
            raise ValueError(
                f"Invalid storage '{self.storage}'. "
                f"Must be one of {VALID_STORAGE_BACKENDS}"
            )

    @classmethod
    def from_env(cls) -> SmartLLMConfig:
        """Build config from environment variables.

        Environment variables:
            SMART_LLM_API_KEY        — OpenRouter API key
            SMART_LLM_LOCAL_URL      — Ollama/LM Studio URL
            SMART_LLM_LOCAL_MODEL    — Preferred local model name
            SMART_LLM_STORAGE        — "sqlite" | "mysql" | "json"
            SMART_LLM_STORAGE_PATH   — File path for sqlite/json
            SMART_LLM_STORAGE_URL    — Connection URL for mysql
            SMART_LLM_PROBE_MINUTES  — Probe interval
            SMART_LLM_SCAN_DAYS      — Catalogue scan interval
            SMART_LLM_LOG_DAYS       — Log retention days
        """
        return cls(
            api_key=os.getenv("SMART_LLM_API_KEY"),
            local_url=os.getenv("SMART_LLM_LOCAL_URL"),
            local_model=os.getenv("SMART_LLM_LOCAL_MODEL"),
            storage=os.getenv("SMART_LLM_STORAGE", "sqlite"),
            storage_path=os.getenv("SMART_LLM_STORAGE_PATH"),
            storage_url=os.getenv("SMART_LLM_STORAGE_URL"),
            probe_interval_minutes=int(os.getenv("SMART_LLM_PROBE_MINUTES", "15")),
            scan_interval_days=int(os.getenv("SMART_LLM_SCAN_DAYS", "30")),
            log_retention_days=int(os.getenv("SMART_LLM_LOG_DAYS", "7")),
        )
