"""Tests for the SmartLLM client."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from smart_llm.client import SmartLLM
from smart_llm.data_models import ProviderResponse


@pytest.fixture
def llm(tmp_path):
    return SmartLLM(
        api_key="test-key",
        storage="json",
        storage_path=str(tmp_path / "test.json"),
    )


def test_init_creates_storage(llm):
    assert llm._storage is not None


def test_init_seeds_registry(llm):
    models = llm._storage.get_active_models()
    assert len(models) > 0


def test_status_returns_dict(llm):
    status = llm.status()
    assert "health" in status
    assert "active_free" in status
    assert "top_model" in status
    assert status["active_free"] >= 5


def test_get_ranked_models(llm):
    ranked = llm.get_ranked_models()
    assert isinstance(ranked, list)
    assert len(ranked) > 0
    # Each item is (model_id, score)
    model_id, score = ranked[0]
    assert isinstance(model_id, str)
    assert isinstance(score, float)


def test_get_logs_empty(llm):
    logs = llm.get_logs()
    assert logs == []


async def test_ask_with_mocked_provider(llm):
    mock_response = ProviderResponse(
        content="The date is 2026-03-15.",
        model_id="google/gemma-3-12b-it:free",
        response_ms=1500,
    )
    with patch.object(llm, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm.ask("What is the date?")
    assert "2026-03-15" in result


async def test_ask_json_returns_dict(llm):
    mock_response = ProviderResponse(
        content='{"name": "Acme", "amount": 100}',
        model_id="google/gemma-3-12b-it:free",
        response_ms=1500,
    )
    with patch.object(llm, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm.ask_json("Extract info")
    assert result["name"] == "Acme"
    assert result["amount"] == 100


async def test_ask_json_handles_markdown_fences(llm):
    mock_response = ProviderResponse(
        content='```json\n{"key": "value"}\n```',
        model_id="google/gemma-3-12b-it:free",
        response_ms=1500,
    )
    with patch.object(llm, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm.ask_json("Extract info")
    assert result["key"] == "value"


async def test_ask_json_handles_embedded_json(llm):
    mock_response = ProviderResponse(
        content='Here is the result: {"key": "value"} and some extra text.',
        model_id="google/gemma-3-12b-it:free",
        response_ms=1500,
    )
    with patch.object(llm, '_call_with_fallback', new_callable=AsyncMock, return_value=mock_response):
        result = await llm.ask_json("Extract info")
    assert result["key"] == "value"


def test_extract_json_direct():
    assert SmartLLM._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert SmartLLM._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_embedded():
    assert SmartLLM._extract_json('Result: {"a": 1} done') == {"a": 1}


def test_extract_json_invalid():
    with pytest.raises(ValueError, match="Could not parse JSON"):
        SmartLLM._extract_json("no json here at all")
