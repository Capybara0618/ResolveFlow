"""The two local-read executors, in one module because they are the same shape (C07.1/C07.2).

``docs/agent-spec.md:34`` says policy search and ``READ_OBSERVATION`` are 本地能力 — local capabilities that are
**not** wrapped as extra microservices. They are also the two actions that behave identically at every boundary
that matters, which is why they live together:

* both spend a **local read** (``docs/agent-spec.md:40``'s 8) and a **search/tool attempt** (the 16) — the two
  budgets are separate and this action is counted in both;
* both reach the SDK as a tool call so the SDK's loop performs them and ``ActionGateMiddleware`` sees them, while
  neither exists in the MCP tool server;
* both record their own stop reason rather than raising, because raising loses it inside the SDK's mcp-1.x
  exception handler (finding #4 in ``reports/agentscope-migration/compatibility.md`` §3);
* both hand back an observation carrying the reference and hash a citation will quote.

They were in ``sdk_runner`` until ``READ_OBSERVATION`` needed the same five decisions written a second time. Two
copies is where behaviour drifts, so the shared shape is a base class and the differences are one method each:
what the action reads, and what its observation says.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolBase

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.actions import (
    MAX_POLICY_TOP_K,
    OBSERVATION_READ_TOOL_NAME,
    POLICY_SEARCH_TOOL_NAME,
)
from resolveflow.harness.budget import BudgetExhaustedError
from resolveflow.harness.control import REASON_TOOL_FAILED
from resolveflow.harness.vocabulary import RunFacts
from resolveflow.policies.index import PolicyIndexNotReadyError

__all__ = [
    "LocalReadBridge",
    "ObservationReadBridge",
    "PolicySearchBridge",
    "observation_text",
]


def observation_text(observation: ToolObservation) -> str:
    """The text of one observation, from the **one** function that produces it.

    Imported from :mod:`resolveflow.harness.context` and re-exported, rather than re-implemented: the packet's P3
    excerpt is cut from that same string, so what a model reads back is the evidence the packet pointed at.
    """
    from resolveflow.harness.context import observation_text as render

    return render(observation)


class LocalReadBridge(ToolBase):
    """One local read, executed against the run's own state, with the shared policy around it.

    Subclasses implement :meth:`_read` (do the work) and :meth:`_observe` (turn the result into the run's
    ``ToolObservation``); this class owns the budget, the stop reasons, the trajectory entry and the tool chunk,
    because those are the parts that must not differ between the two actions.
    """

    def __init__(
        self,
        name: str,
        *,
        description: str,
        input_schema: dict[str, Any],
        facts: RunFacts,
        gate: Any,
        adapter: Any,
        client: Any,
        guard: Any,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.is_concurrency_safe = False
        self.is_read_only = True
        # **Not** an external tool: with `is_external_tool = True` the SDK parks the reply waiting for an
        # `ExternalExecutionResultEvent` and the run ends — the shape for work a *person* must do. These are
        # ordinary reads the loop should make.
        self.is_external_tool = False
        self.is_state_injected = False
        self.is_mcp = False
        self.mcp_name: str | None = None
        self.dangerous_files: list[str] = []
        self.dangerous_directories: list[str] = []
        self._facts = facts
        self._gate = gate
        self._adapter = adapter
        self._client = client
        self._guard = guard
        #: Every call this bridge made, so a test can assert what was asked for and what came back.
        self.calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ the shared policy

    def check_permissions(self, tool_input: dict[str, Any], context: Any) -> Any:
        """Passthrough: the gate is the middleware, and two gates would make a refusal ambiguous."""
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH, message="the action gate decides")

    async def call(self, **kwargs: Any) -> Any:
        from agentscope.tool import ToolChunk
        from agentscope.tool._response import ToolResultState  # type: ignore[attr-defined]

        self.calls.append({"tool": self.name, "arguments": dict(kwargs)})

        # Two reservations, because `docs/agent-spec.md:40` counts this action in two budgets: it is a
        # search/tool attempt ("16次外部工具/检索attempt") and it is one of the 8 local reads
        # (`budget.reserve_local_read`'s own docstring names both actions). Reserving neither was the C06→C07 gap;
        # reserving only one would make the other bound unreachable and its report meaningless.
        try:
            if self._client.durability is not None:
                self._client.durability.before_tool(self.name, dict(kwargs), self._guard)
            self._guard.guard.reserve_tool_attempt()
            self._guard.guard.reserve_local_read()
        except BudgetExhaustedError as exhausted:
            self._gate.note_stop(exhausted.reason_code)
            # A refused attempt produced no evidence, and saying so is what keeps the no-progress rule working:
            # without it `pending_repeat` stays set and the third identical refusal is never counted, so the run
            # burns its model-call budget instead of stopping on the refusal. A test expecting the refusal's own
            # reason caught exactly that (`BUDGET_MODEL_CALLS` where the reason should have been the refusal).
            self._gate.note_evidence(False)
            self._adapter.trajectory.append(
                {"action": self.name, "outcome": "REFUSED", "detail": exhausted.reason_code}
            )
            return ToolChunk(
                content=[TextBlock(type="text", text=f"{exhausted.reason_code}: {exhausted}")],
                state=ToolResultState.ERROR,
            )

        except Exception as failure:  # noqa: BLE001 - preserve fenced refusal outside SDK's legacy MCP handler
            code = self._client.durability.capture_error(failure) if self._client.durability is not None else None
            if code is None:
                raise
            self._gate.note_stop(code)
            return ToolChunk(content=[TextBlock(type="text", text=code)], state=ToolResultState.ERROR)
        try:
            observation = (
                self._client.durability.observe(self.name, dict(kwargs), lambda: self._read(**kwargs),
                                                self._guard, local=True)
                if self._client.durability is not None else self._read(**kwargs)
            )
        except self.refusal_types() as refusal:
            return self._refuse(refusal, **kwargs)
        except Exception as failure:  # noqa: BLE001 - the failure is the run's fact to record
            if self._client.durability is not None:
                self._client.durability.capture_error(failure)
            self._gate.note_stop(REASON_TOOL_FAILED)
            self._gate.note_evidence(False)
            self._adapter.trajectory.append(
                {"action": self.name, "outcome": "FAILED", "detail": str(failure)[:300]}
            )
            return ToolChunk(
                content=[TextBlock(type="text", text=f"TOOL_FAILED: {failure}")],
                state=ToolResultState.ERROR,
            )

        fresh = self._adapter.record_observation(observation)
        self._client.note_observation(observation)
        self._gate.note_evidence(fresh)
        self._last_observation = observation
        self._adapter.trajectory.append(
            {
                "action": self.name,
                "outcome": "OBSERVED",
                "new_evidence": fresh,
                "observation_id": observation.observation_id,
                **self.trajectory_detail(),
            }
        )
        return ToolChunk(
            content=[TextBlock(type="text", text=json.dumps(observation.model_dump(mode="json"), default=str))],
            state=ToolResultState.SUCCESS,
        )

    # ------------------------------------------------------------------ what a subclass provides

    def _read(self, **kwargs: Any) -> ToolObservation:
        raise NotImplementedError

    def refusal_types(self) -> tuple[type[BaseException], ...]:
        """The exceptions that mean "this run cannot do that", as opposed to an environment failure."""
        return ()

    def _refuse(self, refusal: BaseException, **kwargs: Any) -> Any:
        """Record the stop and hand the model an error chunk naming the reason.

        Takes the **exception** rather than a string, because a subclass's refusal carries facts a reader needs and
        a message would flatten them. The first version of this took ``(detail, reason_code)``, and the policy
        index's ``hash_mismatch`` — which distinguishes "nobody indexed this bundle" from "indexed at a different
        hash" — was silently dropped. ``detail_of`` is where a subclass says what else travels.
        """
        from agentscope.tool import ToolChunk
        from agentscope.tool._response import ToolResultState  # type: ignore[attr-defined]

        code = str(getattr(refusal, "reason_code", "") or getattr(refusal, "code", "") or "REFUSED")
        detail = str(refusal)
        self._gate.note_stop(code)
        # No evidence came of this, which is what lets the no-progress rule count it: three identical refusals stop
        # the run instead of being retried until the model-call budget runs out (docs/agent-spec.md:44).
        self._gate.note_evidence(False)
        self._adapter.trajectory.append(
            {
                "action": self.name,
                "outcome": "REFUSED",
                "detail": detail[:300],
                "reason_code": code,
                **self.detail_of(refusal),
            }
        )
        return ToolChunk(
            content=[TextBlock(type="text", text=f"{code}: {detail}")],
            state=ToolResultState.ERROR,
        )

    def detail_of(self, refusal: BaseException) -> dict[str, Any]:
        """Extra structured facts about a refusal, for the trajectory. Empty unless a subclass has some."""
        return {}

    def trajectory_detail(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


class PolicySearchBridge(LocalReadBridge):
    """``SEARCH_POLICY``, executed against the run's own pinned policy index.

    This is the executor C07 was left needing: ``actions._check_policy_search`` validated the action's shape from
    C06.4 onward and ``budget.reserve_local_read`` existed with the comment naming policy search — but nothing
    called either, so a validated ``SEARCH_POLICY`` had no way to run and the local-read budget was unspendable.

    The identity comes from the **run**, never from the action: merchant, pinned bundles and manifest hash are the
    run's facts, and the model supplies only ``query`` and optionally ``top_k``.
    """

    def __init__(
        self,
        index: Any,
        facts: RunFacts,
        gate: Any,
        adapter: Any,
        client: Any,
        guard: Any,
        *,
        embedder: Any = None,
        generation_ids: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            POLICY_SEARCH_TOOL_NAME,
            description=(
                "Search the merchant policy this run is pinned to. Provide a natural-language query; the search is "
                "restricted to the pinned bundles and version and returns whole rules with citable identifiers."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "what to look for, in the customer's words"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_POLICY_TOP_K},
                },
                "required": ["query"],
            },
            facts=facts,
            gate=gate,
            adapter=adapter,
            client=client,
            guard=guard,
        )
        self._index = index
        self._embedder = embedder
        self._generation_ids = generation_ids

    def refusal_types(self) -> tuple[type[BaseException], ...]:
        return (PolicyIndexNotReadyError,)

    def detail_of(self, refusal: BaseException) -> dict[str, Any]:
        """Carry the index's ``hash_mismatch`` through.

        It is the difference between "nobody indexed this bundle" and "the index is at a different version", and an
        operator's next action differs between the two — re-index versus look for a deployment bug. The reason code
        is ``POLICY_INDEX_NOT_READY`` either way, which is the run's own stop reason and the point of giving this
        refusal its own code: a run pinned to an unindexed manifest may retry or escalate, and it may **not** search
        an older version (``docs/policy-rag.md:23``).
        """
        return {"hash_mismatch": bool(getattr(refusal, "hash_mismatch", False))}

    def _read(self, **kwargs: Any) -> ToolObservation:
        query = str(kwargs.get("query") or "")
        top_k = kwargs.get("top_k")
        pinned = self._facts.policy_manifest
        scope = dict(
            merchant_id=str(pinned.get("merchant_id") or self._facts.merchant_id or ""),
            bundle_ids=[str(bundle) for bundle in (pinned.get("bundle_ids") or [])],
            manifest_hash=str(pinned.get("manifest_hash") or ""),
            **({"generation_ids": self._generation_ids} if self._generation_ids is not None else {}),
        )
        # Use the same bounded, pinned complete read as consultation. No new lookup,
        # ranking or eligibility inference: large sets retain the existing dense path.
        hits = self._index.small_context(**scope) if self._generation_ids is not None else None
        complete = hits is not None
        if hits is None:
            hits = self._index.search(**scope, query=query, path="dense",
                top_k=int(top_k) if isinstance(top_k, int) and not isinstance(top_k, bool) else MAX_POLICY_TOP_K,
                embedder=self._embedder)
        observation = _policy_observation(hits, self._facts, query, self._now())
        observation.result["retrieval_context"] = ({"mode": "COMPLETE_SMALL_SET", "count": len(hits)}
                                                   if complete else {"mode": "RANKED"})
        return observation

    def trajectory_detail(self) -> dict[str, Any]:
        observation = getattr(self, "_last_observation", None)
        hits = (observation.result or {}).get("hits", []) if observation is not None else []
        return {"hits": len(hits) if isinstance(hits, list) else 0}


class ObservationReadBridge(LocalReadBridge):
    """``READ_OBSERVATION``, executed against the run's own observation store.

    ``docs/context-engineering.md:31``: 仅访问当前 run 及明确允许继承的材料；不存在 ref 返回 NOT_FOUND，不猜内容或跨
    case 查找。The store is per run and has no case index, so the boundary is a property of the object rather than a
    check a caller applies.
    """

    def __init__(
        self,
        store: Any,
        facts: RunFacts,
        gate: Any,
        adapter: Any,
        client: Any,
        guard: Any,
    ) -> None:
        # The bound is **imported**, not restated. It appears in this schema, in the tool's runtime refusal and in
        # the store's own check; three copies of "4000" would eventually disagree, and the SDK validates against
        # *this* one before execution — so a drifting copy here would silently become the real bound.
        from resolveflow.harness.observation_read import MAX_READ_LIMIT

        super().__init__(
            OBSERVATION_READ_TOOL_NAME,
            description=(
                "Read back part of an observation this run already made. Provide observation_id and optionally "
                "offset and limit (at most 4000 characters). The text is the evidence itself, not a summary."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "observation_id": {"type": "string", "description": "an id from this run's P4 index"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_READ_LIMIT},
                },
                "required": ["observation_id"],
            },
            facts=facts,
            gate=gate,
            adapter=adapter,
            client=client,
            guard=guard,
        )
        self._store = store

    def refusal_types(self) -> tuple[type[BaseException], ...]:
        from resolveflow.harness.observation_read import (
            ObservationNotFoundError,
            ObservationReadRefusedError,
        )

        return (ObservationNotFoundError, ObservationReadRefusedError)

    def _read(self, **kwargs: Any) -> ToolObservation:
        from resolveflow.harness.observation_read import MAX_READ_LIMIT, read_observation

        observation_id = str(kwargs.get("observation_id") or "")
        offset = kwargs.get("offset")
        limit = kwargs.get("limit")
        window = read_observation(
            self._store,
            observation_id=observation_id,
            offset=int(offset) if isinstance(offset, int) and not isinstance(offset, bool) else 0,
            limit=int(limit) if isinstance(limit, int) and not isinstance(limit, bool) else MAX_READ_LIMIT,
        )
        # The observation this read *is*: its own id (so a second read of the same window is the same evidence and
        # the no-progress rule can see that) and the hash of the text it returned. Its source_type/source_ref are
        # the **read** observation's, not the underlying source's, because what the run observed here is the
        # read-back; the underlying reference travels inside the result for a citation to quote.
        digest = hashlib.sha256(window.text.encode("utf-8")).hexdigest()
        return ToolObservation(
            observation_id=f"read:{window.observation_id}@{window.offset}",
            tool_name=OBSERVATION_READ_TOOL_NAME,
            source_type=EvidenceSourceType(window.material["source_type"]) if window.material is not None
            else EvidenceSourceType.POLICY_RULE
            if self._underlying_is_policy(window.observation_id)
            else EvidenceSourceType.ORDER_LINE,
            source_ref=f"observation:{window.observation_id}",
            source_version=f"offset={window.offset}",
            content_hash=digest,
            observed_at=self._now(),
            result=window.as_result(),
        )

    def _underlying_is_policy(self, observation_id: str) -> bool:
        """Whether the observation being read was a policy search.

        Kept honest: a read-back of a policy search is policy evidence, and labelling it ``ORDER_LINE`` would make
        the same text authoritative in the wrong place. The check is on the stored observation's own tool name.
        """
        stored = getattr(self._store, "_by_id", {}).get(observation_id)
        return bool(stored is not None and stored.tool_name == POLICY_SEARCH_TOOL_NAME)

    def trajectory_detail(self) -> dict[str, Any]:
        return {}


def _policy_observation(hits: list[Any], facts: RunFacts, query: str, observed_at: str) -> ToolObservation:
    """The policy search result as the run's own ``ToolObservation``.

    ``source_ref`` is one reference per **hit** inside ``result`` and a bundle-level reference on the observation
    itself: the observation is "the pinned policy set answered this query", while each hit carries the
    ``policy:<bundle>/<chunk>`` reference and Java's ``content_hash`` a citation will quote. Building that here —
    rather than letting the model re-derive it — is what keeps ``docs/agent-spec.md:52``'s "ref 必须实际可见"
    checkable: the reference names bytes this run really read.
    """
    pinned = facts.policy_manifest
    bundle_ids = [str(bundle) for bundle in (pinned.get("bundle_ids") or [])]
    manifest_hash = str(pinned.get("manifest_hash") or "")
    digest = _search_digest(bundle_ids, manifest_hash, query)
    empty = not hits
    return ToolObservation(
        observation_id=f"policy-search-{digest[:32]}",
        tool_name=POLICY_SEARCH_TOOL_NAME,
        source_type=EvidenceSourceType.POLICY_RULE,
        source_ref=_policy_source_ref(bundle_ids),
        source_version=_policy_version(bundle_ids, manifest_hash),
        # Derived from what the search was *over*, so the same query against the same pinned policy is the same
        # observation rather than a new one: a model that asks the same thing twice has learned nothing, and the
        # no-progress rule needs to see that (docs/agent-spec.md:44). A search that found nothing and one that
        # found rules therefore differ, and both are stable.
        content_hash=digest if not empty else _empty_answer_digest(bundle_ids, manifest_hash, query),
        observed_at=observed_at,
        result={
            "query": query,
            "hit_count": len(hits),
            "hits": [
                {
                    "bundle_id": hit.bundle_id,
                    "version": hit.version,
                    "rule_id": hit.rule_id,
                    "chunk_id": hit.chunk_id,
                    "content_hash": hit.content_hash,
                    "title": hit.title,
                    "text": hit.text,
                    "score": round(float(hit.score), 6),
                    "source_ref": hit.source_ref,
                }
                for hit in hits
            ],
        },
    )


def _canonical_search(bundle_ids: list[str], manifest_hash: str, query: str, hits: int | None) -> str:
    payload: dict[str, Any] = {
        "bundles": sorted(bundle_ids),
        "manifest_hash": manifest_hash,
        "query": query,
    }
    if hits is not None:
        payload["hits"] = hits
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _search_digest(bundle_ids: list[str], manifest_hash: str, query: str) -> str:
    """Stable id and hash for a search that produced hits, computed from what it was over."""
    return _canonical_search(bundle_ids, manifest_hash, query, None)


def _empty_answer_digest(bundle_ids: list[str], manifest_hash: str, query: str) -> str:
    """A distinct hash for "the policy is silent", so it can never collide with a real answer's hash.

    A search that matched nothing is a *successful read with an empty answer*, not an error: the index was ready
    and the policy genuinely does not mention the query. Reporting it as ``NOT_FOUND`` would make the model treat
    "the policy is silent" as "the source was unreachable" and retry forever, and giving it the same hash as a
    hits-bearing search would make an empty answer look like new evidence every time it was asked.
    """
    return _canonical_search(bundle_ids, manifest_hash, query, 0)


def _policy_source_ref(bundle_ids: list[str]) -> str:
    """``policy:<first bundle>``, a controlled reference and never a URL (``docs/core-contracts.md:61``)."""
    return f"policy:{bundle_ids[0] if bundle_ids else 'unpinned'}"


def _policy_version(bundle_ids: list[str], manifest_hash: str) -> str:
    """The pin, abbreviated: the full hash is in the observation's ``content_hash`` and in every hit."""
    return f"{bundle_ids[0] if bundle_ids else 'unpinned'}@{manifest_hash[:16]}"
