"""Run-local prompt aliases; expand into the existing strict contract before validation.

The registry is rebuilt from original observations, never from user text or model output.
Only references explicitly rendered in mandatory P2 are eligible for alias citations.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.actions import ActionRefusedError

EVIDENCE_FIELDS = ("observation_id", "source_ref", "source_version", "content_hash")
POLICY_FIELDS = ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")


class ReferenceCatalog:
    def __init__(self, observations: list[ToolObservation]) -> None:
        self.references: dict[str, dict[str, Any]] = {}
        self.read_ids: dict[str, str] = {}
        self._evidence: dict[tuple[Any, ...], tuple[str, ToolObservation]] = {}
        self._policies: dict[tuple[Any, ...], str] = {}
        seen: set[str] = set()
        for observation in observations:
            if observation.observation_id in seen:
                continue
            seen.add(observation.observation_id)
            alias = f"O{len(seen)}"
            self.read_ids[alias] = observation.observation_id
            if observation.error or not observation.source_version or not observation.content_hash:
                continue
            if observation.tool_name == "read_observation":
                continue
            if observation.tool_name == "search_policy":
                hits = (observation.result or {}).get("hits", [])
                for hit in hits if isinstance(hits, list) else []:
                    if isinstance(hit, dict) and all(isinstance(hit.get(k), str) and hit[k] for k in POLICY_FIELDS):
                        key = tuple(hit[k] for k in POLICY_FIELDS)
                        self._policies.setdefault(key, f"P{len(self._policies) + 1}")
            else:
                key = tuple(getattr(observation, k) for k in EVIDENCE_FIELDS)
                self._evidence[key] = (alias, observation)

    def evidence(self, ref: dict[str, Any], *, authority: str | None = None,
                 register: bool = True) -> dict[str, Any] | None:
        found = self._evidence.get(tuple(ref.get(k) for k in EVIDENCE_FIELDS))
        if found is None:
            return None
        alias, observation = found
        if register:
            self.references[alias] = {"kind": "evidence", "ref": {k: ref[k] for k in EVIDENCE_FIELDS}}
        header = {"ref": alias, "tool": observation.tool_name, "source_type": observation.source_type.value,
                  "source_version": observation.source_version}
        if authority is not None:
            header["authority"] = authority
        return header

    def policy(self, hit: dict[str, Any]) -> dict[str, Any]:
        alias = self._policies[tuple(hit[k] for k in POLICY_FIELDS)]
        self.references[alias] = {"kind": "policy", "ref": {k: hit[k] for k in POLICY_FIELDS}}
        return {"ref": alias, **{k: hit[k] for k in ("bundle_id", "version", "rule_id", "text")}}

    def read_alias(self, observation_id: str) -> str:
        return next((key for key, value in self.read_ids.items() if value == observation_id), observation_id)


def expand_references(payload: dict[str, Any], references: dict[str, dict[str, Any]],
                      read_ids: dict[str, str]) -> dict[str, Any]:
    """No inferred citations, automatic additions, or external lookup; unknown aliases fail closed."""
    result = deepcopy(payload)

    def resolve(alias: str, kind: str) -> dict[str, Any]:
        entry = references.get(alias)
        if entry is None or entry["kind"] != kind:
            available = [key for key, row in references.items() if row["kind"] == kind]
            raise ActionRefusedError(
                f"Unknown or wrong-kind {kind} reference {alias[:40]!r}; "
                f"available {kind} aliases: {','.join(available[:24]) or '(none)'}. Use current P2 refs.",
                reason_code="ACTION_CITATION_INVALID")
        return deepcopy(entry["ref"])

    for field, kind in (("evidence_refs", "evidence"), ("policy_refs", "policy")):
        refs = result.get(field)
        if isinstance(refs, list):
            result[field] = [resolve(ref, kind) if isinstance(ref, str) else ref for ref in refs]
    findings = result.get("review_findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict) and isinstance(finding.get("observation_ids"), list):
                finding["observation_ids"] = [
                    resolve(ref, "evidence")["observation_id"] if isinstance(ref, str) and ref in read_ids else ref
                    for ref in finding["observation_ids"]]
    if result.get("kind") == "READ_OBSERVATION" and isinstance(result.get("observation_id"), str):
        ref = result["observation_id"]
        result["observation_id"] = read_ids.get(ref, ref)
    return result
