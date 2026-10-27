"""Synthetic saved-tool adapter for regression tests; no external calls."""

from copy import deepcopy
from typing import Any

from resolveflow.harness.context import canonical_json
from resolveflow.support.guide import guide_source


class SavedSources:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[dict[str, Any]] = []
        for call in calls:
            if call["kind"] == "tool":
                key = canonical_json(call["request_json"])
                self.responses.setdefault(key, []).append(deepcopy(call["response_json"]))

    def invoke(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        key = canonical_json({"name": name, "arguments": arguments})
        responses = self.responses.get(key, [])
        if responses:
            result = responses.pop(0)
            origin = "SAVED_TOOL_RESULT"
        elif name == "get_support_guide" and not arguments:
            result, origin = [guide_source()], "CURRENT_PUBLIC_GUIDE_PRELOAD"
        else:
            raise AssertionError(f"offline record missing: {key}")
        self.calls.append({"name": name, "arguments": arguments, "origin": origin})
        return deepcopy(result)

    def read(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self.invoke(name, arguments)
        assert len(result) == 1
        return result[0]

    def search(self, query: str, top_k: int, **options: Any) -> list[Any]:
        return self.invoke("search_policy", {"query": query, "top_k": top_k, **options})
