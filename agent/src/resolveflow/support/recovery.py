"""Reconstructable source retry state; no fabricated answer or automatic business handoff."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.harness.context import canonical_json


class SourceRecovery:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}

    def blocked(self, request: dict[str, Any]) -> bool:
        state = self.states.get(canonical_json(request))
        return state is not None and not state["retry_allowed"]

    def observe(self, request: dict[str, Any], results: list[dict[str, Any]]) -> None:
        key = canonical_json(request)
        error = next((r for r in results if "error" in r), None)
        if error is None:
            self.states.pop(key, None)
        elif error["error"] != "SOURCE_RETRY_EXHAUSTED":
            failures = self.states.get(key, {}).get("failures", 0) + 1
            self.states[key] = {
                "tool_name": request["name"], "arguments": request["arguments"],
                "error": error["error"], "failures": failures,
                "retry_allowed": error.get("retryable") is True and failures < 2,
            }

    def packet(self) -> list[dict[str, Any]]:
        return deepcopy(list(self.states.values()))
