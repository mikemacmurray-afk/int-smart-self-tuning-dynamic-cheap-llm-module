"""Tests for JSON storage backend — validates the StorageBackend contract."""

import pytest
from datetime import datetime, timedelta
from smart_llm.storage.json_backend import JSONBackend
from smart_llm.data_models import ModelInfo, ProbeResult, CallRecord


@pytest.fixture
def backend(tmp_path):
    path = str(tmp_path / "test_state.json")
    b = JSONBackend(path=path)
    b.initialize()
    yield b
    b.close()


def test_upsert_and_get_model(backend):
    m = ModelInfo(model_id="test/model", tier="free", provider="openrouter", status="active")
    backend.upsert_model(m)
    models = backend.get_active_models()
    assert len(models) == 1
    assert models[0].model_id == "test/model"


def test_get_active_models_by_tier(backend):
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="b", tier="cheap", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="c", tier="free", provider="or", status="retired"))

    free = backend.get_active_models(tier="free")
    assert len(free) == 1
    assert free[0].model_id == "a"

    cheap = backend.get_active_models(tier="cheap")
    assert len(cheap) == 1

    all_active = backend.get_active_models()
    assert len(all_active) == 2


def test_get_all_models(backend):
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="b", tier="free", provider="or", status="retired"))

    all_models = backend.get_all_models()
    assert len(all_models) == 2


def test_retire_model(backend):
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    backend.retire_model("a")
    assert len(backend.get_active_models()) == 0
    all_models = backend.get_all_models()
    assert all_models[0].status == "retired"


def test_count_models(backend):
    assert backend.count_models() == 0
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    assert backend.count_models() == 1
    backend.upsert_model(ModelInfo(model_id="b", tier="cheap", provider="or", status="active"))
    assert backend.count_models() == 2


def test_upsert_model_update(backend):
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="retired"))
    assert backend.count_models() == 1
    models = backend.get_all_models()
    assert models[0].status == "retired"


def test_probe_upsert_and_get(backend):
    p = ProbeResult(model_id="test/model", response_ms=1500, status="ok")
    backend.upsert_probe(p)
    result = backend.get_probe("test/model")
    assert result is not None
    assert result.response_ms == 1500
    assert result.status == "ok"


def test_probe_get_nonexistent(backend):
    assert backend.get_probe("nonexistent") is None


def test_probe_upsert_update(backend):
    backend.upsert_probe(ProbeResult(model_id="a", response_ms=1000, status="ok"))
    backend.upsert_probe(ProbeResult(model_id="a", response_ms=2000, status="timeout"))
    result = backend.get_probe("a")
    assert result.response_ms == 2000
    assert result.status == "timeout"


def test_get_all_probes(backend):
    backend.upsert_probe(ProbeResult(model_id="a", response_ms=100, status="ok"))
    backend.upsert_probe(ProbeResult(model_id="b", response_ms=200, status="ok"))
    probes = backend.get_all_probes()
    assert len(probes) == 2


def test_call_record_and_history(backend):
    r = CallRecord(model_id="test/model", response_ms=2000, status="ok")
    backend.record_call(r)
    history = backend.get_history("test/model", since=datetime.now() - timedelta(hours=1))
    assert len(history) == 1
    assert history[0].response_ms == 2000


def test_call_history_filtering(backend):
    backend.record_call(CallRecord(model_id="a", response_ms=100, status="ok"))
    backend.record_call(CallRecord(model_id="b", response_ms=200, status="ok"))

    history_a = backend.get_history("a", since=datetime.now() - timedelta(hours=1))
    assert len(history_a) == 1
    assert history_a[0].model_id == "a"


def test_get_all_history(backend):
    backend.record_call(CallRecord(model_id="a", response_ms=100, status="ok"))
    backend.record_call(CallRecord(model_id="b", response_ms=200, status="ok"))

    history = backend.get_all_history(since=datetime.now() - timedelta(hours=1))
    assert len(history) == 2


def test_prune_old_records(backend):
    old = CallRecord(
        model_id="test/model", response_ms=100, status="ok",
        called_at=datetime.now() - timedelta(days=10),
    )
    new = CallRecord(model_id="test/model", response_ms=200, status="ok")
    backend.record_call(old)
    backend.record_call(new)

    pruned = backend.prune_old_records(before=datetime.now() - timedelta(days=7))
    assert pruned == 1

    history = backend.get_all_history(since=datetime.now() - timedelta(days=30))
    assert len(history) == 1
    assert history[0].response_ms == 200


def test_persistence(tmp_path):
    path = str(tmp_path / "persist.json")

    b1 = JSONBackend(path=path)
    b1.initialize()
    b1.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    b1.upsert_probe(ProbeResult(model_id="a", response_ms=500, status="ok"))
    b1.close()

    b2 = JSONBackend(path=path)
    b2.initialize()
    assert len(b2.get_active_models()) == 1
    assert b2.get_probe("a").response_ms == 500
    b2.close()


def test_status_summary(backend):
    backend.upsert_model(ModelInfo(model_id="a", tier="free", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="b", tier="cheap", provider="or", status="active"))
    backend.upsert_model(ModelInfo(model_id="c", tier="paid", provider="or", status="active"))

    status = backend.get_status_summary()
    assert status["total_models"] == 3
    assert status["active_free"] == 1
    assert status["active_cheap"] == 1
    assert status["active_paid"] == 1
