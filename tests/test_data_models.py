"""Tests for data models."""

import pytest
from datetime import datetime
from smart_llm.data_models import ModelInfo, ProbeResult, CallRecord, ProviderResponse


def test_model_info_creation():
    m = ModelInfo(
        model_id="google/gemma-3-12b-it:free",
        tier="free",
        provider="openrouter",
        status="active",
    )
    assert m.model_id == "google/gemma-3-12b-it:free"
    assert m.tier == "free"
    assert m.quality_score is None
    assert m.added_at is not None


def test_model_info_defaults():
    m = ModelInfo(model_id="x", tier="free", provider="openrouter")
    assert m.status == "candidate"
    assert m.quality_score is None
    assert m.last_scanned_at is None


def test_model_info_tier_validation():
    with pytest.raises(ValueError, match="Invalid tier"):
        ModelInfo(model_id="x", tier="invalid", provider="openrouter", status="active")


def test_model_info_status_validation():
    with pytest.raises(ValueError, match="Invalid status"):
        ModelInfo(model_id="x", tier="free", provider="openrouter", status="invalid")


def test_model_info_all_valid_tiers():
    for tier in ("local", "free", "cheap", "paid"):
        m = ModelInfo(model_id="x", tier=tier, provider="p")
        assert m.tier == tier


def test_probe_result_creation():
    p = ProbeResult(model_id="test/model", response_ms=1500, status="ok")
    assert p.probed_at is not None
    assert p.response_ms == 1500
    assert p.status == "ok"


def test_probe_result_defaults():
    p = ProbeResult(model_id="test/model")
    assert p.response_ms is None
    assert p.status == "unknown"


def test_call_record_auto_fields():
    c = CallRecord(model_id="test/model", response_ms=2000, status="ok")
    assert c.day_of_week == datetime.now().weekday()
    assert c.hour_of_day == datetime.now().hour


def test_call_record_explicit_fields():
    c = CallRecord(
        model_id="test/model",
        response_ms=2000,
        status="ok",
        day_of_week=3,
        hour_of_day=14,
    )
    assert c.day_of_week == 3
    assert c.hour_of_day == 14


def test_provider_response():
    r = ProviderResponse(content="hello", model_id="test/model", response_ms=100)
    assert r.content == "hello"
    assert r.token_count is None
    assert r.raw_response is None
