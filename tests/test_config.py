"""Tests for configuration."""

import pytest
from smart_llm.config import SmartLLMConfig


def test_default_config():
    cfg = SmartLLMConfig()
    assert cfg.storage == "sqlite"
    assert cfg.probe_interval_minutes == 15
    assert cfg.scan_interval_days == 30
    assert cfg.log_retention_days == 7
    assert cfg.api_key is None


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SMART_LLM_API_KEY", "test-key")
    monkeypatch.setenv("SMART_LLM_STORAGE", "json")
    monkeypatch.setenv("SMART_LLM_PROBE_MINUTES", "5")

    cfg = SmartLLMConfig.from_env()
    assert cfg.api_key == "test-key"
    assert cfg.storage == "json"
    assert cfg.probe_interval_minutes == 5


def test_config_override():
    cfg = SmartLLMConfig(api_key="override-key", storage="mysql")
    assert cfg.api_key == "override-key"
    assert cfg.storage == "mysql"


def test_config_invalid_storage():
    with pytest.raises(ValueError, match="Invalid storage"):
        SmartLLMConfig(storage="redis")


def test_config_all_valid_backends():
    for backend in ("sqlite", "mysql", "json"):
        cfg = SmartLLMConfig(storage=backend)
        assert cfg.storage == backend


def test_config_env_defaults(monkeypatch):
    # Clear any existing env vars
    monkeypatch.delenv("SMART_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SMART_LLM_STORAGE", raising=False)

    cfg = SmartLLMConfig.from_env()
    assert cfg.api_key is None
    assert cfg.storage == "sqlite"
    assert cfg.log_retention_days == 7
