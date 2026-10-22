"""Bounded actual execution history; rebuilt from journaled tools, never model narration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class ReadActivity:
    def __init__(self) -> None:
        self.groups: list[dict[str, Any]] = []
        self.calls = 0
        self.omitted = 0

    def record(self, request: dict[str, Any], progress: dict[str, Any], results: list[dict[str, Any]]) -> None:
        self.calls += 1
        item = {"tool_name": request["name"], "arguments": deepcopy(request["arguments"]),
                "outcome": progress["outcome"], "source_refs": list(progress["source_refs"]), "attempts": 1}
        errors = list(dict.fromkeys(str(r["error"]) for r in results if "error" in r))
        if errors:
            item["errors"] = errors
        prior = self.groups[-1] if self.groups else None
        keys = ("tool_name", "arguments", "source_refs", "errors")
        if prior is not None and all(prior.get(k) == item.get(k) for k in keys):
            prior.update(outcome=item["outcome"], attempts=prior["attempts"] + 1)
        else:
            self.groups.append(item)
            if len(self.groups) > 3:
                self.groups.pop(0)
                self.omitted += 1

    def packet(self) -> dict[str, Any]:
        if self.calls < 2:
            return {}
        return {"recent_actions": deepcopy(self.groups), "omitted_action_groups": self.omitted}
