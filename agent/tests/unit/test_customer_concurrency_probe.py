"""A stable inference owner must execute every request without caching or losing per-call timing."""

import threading
from concurrent.futures import ThreadPoolExecutor

from scripts.customer_rag_concurrency_probe import OwnedEncoder


def test_concurrent_calls_execute_on_one_thread_and_preserve_results():
    class Encoder:
        def __init__(self):
            self.calls = []

        def embed_profiled(self, texts):
            self.calls.append((threading.get_ident(), texts))
            return [[float(texts[0])]], {"embedding_wait_ms": 0.0, "query_encoding_ms": 1.0}

    encoder = Encoder()
    owner = OwnedEncoder(encoder)
    try:
        with ThreadPoolExecutor(max_workers=4) as callers:
            futures = [callers.submit(owner.embed_profiled, [str(i)]) for i in range(12)]
            rows = [f.result() for f in futures]
        assert [row[0] for row in rows] == [[[float(i)]] for i in range(12)]
        assert len(encoder.calls) == 12
        assert len({identity for identity, _ in encoder.calls}) == 1
        assert all(profile["embedding_wait_ms"] >= 0 and profile["query_encoding_ms"] == 1.0 for _, profile in rows)
    finally:
        owner.close()
