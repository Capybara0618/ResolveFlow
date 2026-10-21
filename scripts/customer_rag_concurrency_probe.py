"""After observing threaded slowdown, isolate embedding execution ownership without changing retrieval results."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from resolveflow.policies.retrieval import embedder  # noqa: E402
from scripts.customer_rag_benchmark import EMBEDDING_PATH, Search, concurrent, verify, write_new  # noqa: E402
from scripts.customer_rag_rerank import digest  # noqa: E402
from scripts.evaluation.customer_knowledge import load_dataset  # noqa: E402

MANIFEST = ROOT / "evals/customer-rag-v5/concurrency-manifest-v2.json"


class OwnedEncoder:
    """One stable inference thread, with explicit caller queue time; no query/result caching."""

    def __init__(self, encoder):
        self.encoder = encoder
        self.executor = ThreadPoolExecutor(max_workers=1)

    def embed_profiled(self, texts):
        submitted = time.perf_counter()

        def call():
            queue_ms = (time.perf_counter() - submitted) * 1000
            values, profile = self.encoder.embed_profiled(texts)
            profile = {
                **profile,
                "embedding_owner_queue_ms": queue_ms,
                "embedding_wait_ms": profile["embedding_wait_ms"] + queue_ms,
            }
            return values, profile

        return self.executor.submit(call).result()

    def close(self):
        self.executor.shutdown(wait=True)


def freeze():
    base = json.loads((ROOT / "evals/customer-rag-v5/manifest.json").read_text(encoding="utf-8"))
    verify(base)
    write_new(
        MANIFEST,
        {
            "version": "customer-embedding-thread-ownership-probe-v1",
            "phase": (
                "After first performance observed; mechanism probe, "
                "not a hidden replacement of original measurements."
            ),
            "inputs": {
                **base["inputs"],
                **{
                    p: digest(ROOT / p)
                    for p in [
                        "scripts/customer_rag_concurrency_probe.py",
                        "reports/customer-rag-v5/performance.json",
                        "agent/tests/unit/test_customer_concurrency_probe.py",
                    ]
                },
            },
            "modes": ["direct-shared-lock", "one-owner-thread"],
            "concurrency": [1, 4],
            "n": 40,
            "new_chat_api_calls": 0,
            "production_adoption": False,
        },
    )


def evaluate(output):
    if output.exists():
        raise FileExistsError("probe output immutable")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for path, sha in manifest["inputs"].items():
        if digest(ROOT / path) != sha:
            raise ValueError("probe input changed: " + path)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    knowledge, queries = load_dataset(ROOT)
    cases = [q for q in queries["cases"] if q["split"] == "dev"]
    encoder = embedder(str(EMBEDDING_PATH))
    vectors = encoder.embed([d["text"] for d in knowledge["documents"]])
    tokenizer = load_tokenizer()
    direct = Search(knowledge, encoder, vectors, None, tokenizer)
    direct.run(cases[0], "rrf")
    baseline = concurrent(direct, cases)
    owner = OwnedEncoder(encoder)
    try:
        # Establish the same four-thread torch setting on the one inference owner before measuring.
        owner.executor.submit(torch.set_num_threads, 4).result()
        proposed = Search(knowledge, owner, vectors, None, tokenizer)
        proposed.run(cases[0], "rrf")
        owned = concurrent(proposed, cases)
    finally:
        owner.close()
    expected = {r["id"]: r["packet_sha256"] for group in baseline for r in group["rows"]}
    if any(expected[r["id"]] != r["packet_sha256"] for group in owned for r in group["rows"]):
        raise ValueError("inference ownership changed retrieval output")
    write_new(
        output,
        {
            "manifest_sha256": digest(MANIFEST),
            "scope": "Same CPU encoder and queries; no CE/GPU/HTTP/DB.",
            "same_packet_hashes": True,
            "torch": torch.__version__,
            "direct-shared-lock": baseline,
            "one-owner-thread": owned,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.output:
        evaluate(args.output)
    else:
        parser.error("choose --freeze or --output")
