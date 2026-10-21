"""Shared weights must stay lazy, serialize inference and never share conversation state."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from resolveflow.policies.retrieval import SentenceTransformerEmbedder


def fake_stack(monkeypatch, factory):
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=factory))
    monkeypatch.setattr("resolveflow.policies.segments.encoder_tokens", lambda text, tokenizer: len(text))


def test_shared_encoder_loads_once_and_serializes_concurrent_inference(monkeypatch):
    loads = []
    active = 0

    class Model:
        tokenizer = None
        max_seq_length = 512

        def __init__(self, path):
            loads.append(path)
            time.sleep(0.01)

        def encode(self, texts, **kwargs):
            nonlocal active
            assert active == 0
            active += 1
            time.sleep(0.01)
            active -= 1
            return [[1.0, 0.0] for _ in texts]

    fake_stack(monkeypatch, Model)
    encoder = SentenceTransformerEmbedder("local-snapshot")
    assert loads == []
    barrier = threading.Barrier(4)

    def run(_):
        barrier.wait(timeout=5)
        return encoder.embed_profiled(["question"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run, range(4)))
    assert loads == ["local-snapshot"]
    assert all(vectors == [[1.0, 0.0]] for vectors, _ in results)
    assert sum(profile["model_load_ms"] > 0 for _, profile in results) == 1
    assert len({id(profile) for _, profile in results}) == 4
    assert all(set(profile) == {"embedding_wait_ms", "model_load_ms", "query_encoding_ms"} for _, profile in results)


def test_failed_load_is_retried_and_oversize_query_is_still_refused(monkeypatch):
    attempts = []

    def load(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("local weights unavailable")
        return SimpleNamespace(tokenizer=None, max_seq_length=2, encode=lambda texts, **kwargs: [[1.0, 0.0]])

    fake_stack(monkeypatch, load)
    encoder = SentenceTransformerEmbedder("snapshot")
    with pytest.raises(OSError):
        encoder.embed(["ok"])
    assert encoder.embed(["ok"]) == [[1.0, 0.0]]
    with pytest.raises(ValueError, match="exceeds encoder window"):
        encoder.embed(["oversize"])
    assert attempts == ["snapshot", "snapshot"]


def test_empty_input_does_not_load_weights(monkeypatch):
    fake_stack(monkeypatch, lambda path: pytest.fail("must remain lazy"))
    assert SentenceTransformerEmbedder("snapshot").embed([]) == []


def test_app_resource_reuses_only_encoder_and_clears_at_shutdown(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from resolveflow.api.app import create_app
    from resolveflow.support.embeddings import SupportEmbeddings

    created = []

    def factory(local_path):
        result = object()
        created.append((local_path, result))
        return result

    monkeypatch.setattr("resolveflow.support.embeddings.embedder", factory)
    pool = SupportEmbeddings()
    assert created == []
    with ThreadPoolExecutor(max_workers=4) as executor:
        encoders = list(executor.map(lambda _: pool.get("A"), range(8)))
    assert len(created) == 1 and all(e is encoders[0] for e in encoders)
    assert pool.get("B") is not encoders[0]
    pool.clear()
    assert pool.get("B") is not created[1][1]
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with TestClient(app):
        first_pool = app.state.support_embeddings
        first = first_pool.get("A")
        assert first_pool.get("A") is first
    with TestClient(app):
        assert app.state.support_embeddings is not first_pool
        assert app.state.support_embeddings.get("A") is not first
    # The prior lifespan released its cached weights too.
    assert first_pool.get("A") is not first


def test_index_enabled_startup_prewarms_shared_encoder_before_health(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from resolveflow.api.app import create_app

    calls = []

    class Encoder:
        def embed(self, texts):
            calls.append(texts)
            return [[1.0]]

    encoder = Encoder()
    lexical = []
    monkeypatch.setattr("resolveflow.support.embeddings.embedder", lambda local_path: encoder)
    monkeypatch.setattr("resolveflow.support.embeddings.tokenize", lambda text: lexical.append(text))
    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", "1")
    monkeypatch.setenv("RESOLVEFLOW_EMBEDDING_PATH", "snapshot")
    monkeypatch.delenv("RESOLVEFLOW_SUPPORT_PREWARM", raising=False)
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with TestClient(app) as client:
        assert calls and client.get("/health").status_code == 200
        assert app.state.support_embeddings.get("snapshot") is encoder
        assert len(calls) == 1 and app.state.support_warmup["status"] == "READY"
        assert len(lexical) == 1


@pytest.mark.parametrize("policy,prewarm", [("0", "1"), ("1", "0")])
def test_startup_stays_lazy_when_index_or_prewarm_disabled(monkeypatch, tmp_path, policy, prewarm):
    from fastapi.testclient import TestClient

    from resolveflow.api.app import create_app

    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", policy)
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_PREWARM", prewarm)
    monkeypatch.setattr("resolveflow.support.embeddings.embedder", lambda **kwargs: pytest.fail("must stay lazy"))
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.support_warmup["status"] == "DISABLED"


def test_prewarm_failure_does_not_publish_ready_or_retain_cached_encoder(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from resolveflow.api.app import create_app

    class Encoder:
        def embed(self, texts):
            raise OSError("local weights unavailable")

    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", "1")
    monkeypatch.delenv("RESOLVEFLOW_SUPPORT_PREWARM", raising=False)
    monkeypatch.setattr("resolveflow.support.embeddings.embedder", lambda local_path: Encoder())
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with pytest.raises(OSError, match="local weights unavailable"), TestClient(app):
        pytest.fail("failed prewarm must stop startup")
    assert app.state.support_warmup["status"] == "FAILED"
    assert app.state.support_embeddings._encoder is None
