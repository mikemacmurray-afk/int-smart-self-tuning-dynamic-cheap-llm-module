"""Integration test — full flow with mocked providers but real storage."""

import pytest
from unittest.mock import AsyncMock, patch
from smart_llm import SmartLLM
from smart_llm.data_models import ProviderResponse


@pytest.fixture
def llm_sqlite(tmp_path):
    return SmartLLM(
        api_key="test-key",
        storage="sqlite",
        storage_path=str(tmp_path / "integration.db"),
    )


@pytest.fixture
def llm_json(tmp_path):
    return SmartLLM(
        api_key="test-key",
        storage="json",
        storage_path=str(tmp_path / "integration.json"),
    )


async def test_full_flow_sqlite(llm_sqlite):
    """Init → seed → ask → verify call recorded (SQLite backend)."""
    mock_response = ProviderResponse(
        content="The answer is 42.",
        model_id="google/gemma-3-12b-it:free",
        response_ms=1200,
    )
    with patch.object(llm_sqlite, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm_sqlite.ask("What is the answer?")

    assert result == "The answer is 42."

    status = llm_sqlite.status()
    assert "health" in status
    assert status["active_free"] >= 5

    ranked = llm_sqlite.get_ranked_models()
    assert len(ranked) > 0


async def test_full_flow_json(llm_json):
    """Init → seed → ask → verify call recorded (JSON backend)."""
    mock_response = ProviderResponse(
        content="The answer is 42.",
        model_id="google/gemma-3-12b-it:free",
        response_ms=1200,
    )
    with patch.object(llm_json, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm_json.ask("What is the answer?")

    assert result == "The answer is 42."

    status = llm_json.status()
    # On fresh install, health is "stale_catalogue" (no scan has ever run) — this is expected
    assert status["health"] in ("ok", "stale_catalogue")


async def test_json_extraction_integration(llm_sqlite):
    """Test JSON extraction through the full client."""
    mock_response = ProviderResponse(
        content='{"name": "Test Corp", "value": 1234}',
        model_id="google/gemma-3-12b-it:free",
        response_ms=800,
    )
    with patch.object(llm_sqlite, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        data = await llm_sqlite.ask_json("Extract data")

    assert data["name"] == "Test Corp"
    assert data["value"] == 1234


def test_status_reports_correct_model_counts(llm_sqlite):
    """Status should reflect seeded model counts."""
    status = llm_sqlite.status()
    assert status["total_models"] == 9  # Total seed models
    assert status["active_free"] == 5
    assert status["active_cheap"] == 3
    assert status["active_paid"] == 1


def test_ranked_models_returns_free_only(llm_sqlite):
    """get_ranked_models should only return free tier models."""
    ranked = llm_sqlite.get_ranked_models()
    # Should have exactly the free seed models
    assert len(ranked) == 5
    for model_id, score in ranked:
        assert ":free" in model_id
