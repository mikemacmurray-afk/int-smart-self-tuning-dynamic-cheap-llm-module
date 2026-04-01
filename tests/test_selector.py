"""Tests for the model selector / ranking engine."""

import pytest
from datetime import datetime, timedelta
from smart_llm.selector import ModelSelector, SEED_MODELS
from smart_llm.data_models import ModelInfo, ProbeResult, CallRecord
from smart_llm.storage.json_backend import JSONBackend


@pytest.fixture
def storage(tmp_path):
    b = JSONBackend(path=str(tmp_path / "test.json"))
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def selector(storage):
    return ModelSelector(storage=storage)


def test_seed_models_has_free():
    """Seed models list should have at least 5 free models."""
    free = [m for m in SEED_MODELS if m["tier"] == "free"]
    assert len(free) >= 5


def test_seed_models_has_cheap():
    """Seed models should include cheap tier."""
    cheap = [m for m in SEED_MODELS if m["tier"] == "cheap"]
    assert len(cheap) >= 2


def test_seed_models_has_paid():
    """Seed models should include paid fallback."""
    paid = [m for m in SEED_MODELS if m["tier"] == "paid"]
    assert len(paid) >= 1


def test_seed_registry_first_run(selector, storage):
    """First call to seed should populate the registry."""
    selector.seed_registry()
    models = storage.get_active_models()
    assert len(models) == len(SEED_MODELS)


def test_seed_registry_idempotent(selector, storage):
    """Second call to seed should be a no-op."""
    selector.seed_registry()
    selector.seed_registry()
    assert storage.count_models() == len(SEED_MODELS)


def test_get_ranked_models_no_probes(selector):
    """With no probe data, all models get neutral scores."""
    selector.seed_registry()
    ranked = selector.get_ranked_models()
    assert len(ranked) > 0
    # All should have neutral-ish scores
    for _, score in ranked:
        assert 0.2 <= score <= 0.8


def test_fast_probe_boosts_ranking(selector, storage):
    """A model with a fast probe result should rank higher."""
    selector.seed_registry()
    storage.upsert_probe(ProbeResult(
        model_id="google/gemma-3-27b-it:free",
        response_ms=1500,
        status="ok",
    ))
    ranked = selector.get_ranked_models()
    assert ranked[0][0] == "google/gemma-3-27b-it:free"


def test_failed_probe_demotes_model(selector, storage):
    """A model with a failed probe should rank lower."""
    selector.seed_registry()
    # Give one model a good probe
    storage.upsert_probe(ProbeResult(
        model_id="google/gemma-3-12b-it:free",
        response_ms=1500,
        status="ok",
    ))
    # Give another model a failed probe
    storage.upsert_probe(ProbeResult(
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        response_ms=None,
        status="error",
    ))
    ranked = selector.get_ranked_models()
    model_ids = [m for m, _ in ranked]
    # Failed model should be below the OK model
    ok_idx = model_ids.index("google/gemma-3-12b-it:free")
    err_idx = model_ids.index("meta-llama/llama-3.3-70b-instruct:free")
    assert ok_idx < err_idx


def test_get_ordered_models_returns_all_tiers(selector):
    """get_ordered_models should return all tiers."""
    selector.seed_registry()
    ordered, timeout = selector.get_ordered_models()
    assert len(ordered) == len(SEED_MODELS)
    assert timeout in (12, 25, 35)


def test_dynamic_timeout_aggressive(selector, storage):
    """Fast probe should produce aggressive timeout."""
    selector.seed_registry()
    storage.upsert_probe(ProbeResult(
        model_id="google/gemma-3-12b-it:free",
        response_ms=1000,
        status="ok",
    ))
    _, timeout = selector.get_ordered_models()
    assert timeout == 12


def test_dynamic_timeout_moderate(selector, storage):
    """Slow probe should produce moderate timeout."""
    selector.seed_registry()
    storage.upsert_probe(ProbeResult(
        model_id="google/gemma-3-12b-it:free",
        response_ms=4000,
        status="ok",
    ))
    _, timeout = selector.get_ordered_models()
    assert timeout == 25


def test_dynamic_timeout_conservative(selector):
    """No probes should produce conservative timeout."""
    selector.seed_registry()
    _, timeout = selector.get_ordered_models()
    assert timeout == 35


def test_get_models_to_probe_all_stale(selector):
    """All models should need probing if no probes exist."""
    selector.seed_registry()
    to_probe = selector.get_models_to_probe()
    free_count = len([m for m in SEED_MODELS if m["tier"] == "free"])
    assert len(to_probe) == free_count


def test_get_models_to_probe_none_stale(selector, storage):
    """No models should need probing if all probes are fresh."""
    selector.seed_registry()
    for m in SEED_MODELS:
        if m["tier"] == "free":
            storage.upsert_probe(ProbeResult(
                model_id=m["model_id"],
                response_ms=1000,
                status="ok",
            ))
    to_probe = selector.get_models_to_probe()
    assert len(to_probe) == 0


def test_record_call(selector, storage):
    """record_call should add to history."""
    selector.record_call("test/model", response_ms=1500, status="ok")
    history = storage.get_all_history(since=datetime.now() - timedelta(hours=1))
    assert len(history) == 1
    assert history[0].model_id == "test/model"
