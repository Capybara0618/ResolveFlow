"""Offline saved-decision replay and wait decomposition; never sends provider or business HTTP."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from resolveflow.harness.model import MockModelClient
from resolveflow.harness.token_counting import InputCounter, load_tokenizer
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/customer-latency-browser-v1/runtime-results.json"


class Script(MockModelClient):
    provider = "deepseek"
    model_id = "deepseek-flash"


class SavedSources:
    def __init__(self, calls):
        self.calls = deepcopy([c for c in calls if c["kind"] == "tool"])

    def take(self, name, arguments):
        call = self.calls.pop(0)
        assert call["request_json"] == {"name": name, "arguments": arguments}
        return deepcopy(call["response_json"])

    def read(self, name, arguments):
        return self.take(name, arguments)[0]

    def search(self, query, top_k):
        return self.take("search_policy", {"query": query, "top_k": top_k})


def replay():
    saved = json.loads(SOURCE.read_text(encoding="utf-8"))["support_runs"][0]
    request = SupportInput.model_validate(saved["input_json"])
    request.deadline_at = datetime.now(UTC) + timedelta(seconds=120)
    script = [c["response_json"]["decision"] for c in saved["calls"] if c["kind"] == "model"]
    sources = SavedSources(saved["calls"])
    model = Script(mode="live", script=deepcopy(script))
    started = time.perf_counter()
    result = SupportAgent(request, model, sources, architecture="orchestrated-v1").run()
    elapsed = (time.perf_counter() - started) * 1000
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert not sources.calls and model.calls == 3
    return result, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "never overwrite previous measurements"
    started = time.perf_counter()
    load_tokenizer()  # Same pinned offline tokenizer used by live Flash; no network.
    tokenizer_load_ms = (time.perf_counter() - started) * 1000
    durations = []
    for _ in range(5):
        result, elapsed = replay()
        durations.append(elapsed)
    row = json.loads(SOURCE.read_text(encoding="utf-8"))["support_runs"][0]
    model_calls = [c for c in row["calls"] if c["kind"] == "model"]
    boundaries = []
    for before, after in pairwise(model_calls):
        boundaries.append({"from_model": before["position"], "to_model": after["position"],
            "journal_start_gap_ms": (datetime.fromisoformat(after["created_at"])
                                     - datetime.fromisoformat(before["created_at"])).total_seconds() * 1000})
    report = {"source": str(SOURCE.relative_to(ROOT)), "provider_requests": 0,
        "business_http_requests": 0, "tokenizer_load_ms": tokenizer_load_ms,
        "saved_decision_sdk_replay_ms": durations, "replay_median_ms": statistics.median(durations),
        "journal_boundaries": boundaries,
        "boundary_limit": "journal created_at precedes provider start; gaps include local guards/tools, not exact provider latency",
        "answer": result["answer"], "model_calls": 3,
        "token_counting_version": InputCounter().version}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print({k: report[k] for k in ("tokenizer_load_ms", "replay_median_ms", "journal_boundaries")})


if __name__ == "__main__":
    main()
