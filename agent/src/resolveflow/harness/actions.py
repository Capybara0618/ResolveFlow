"""The action ABI: what a model may ask for, and what the Harness refuses (C06.4①).

``docs/agent-spec.md:2`` fixes the vocabulary — READ_TOOL, SEARCH_POLICY, READ_OBSERVATION, ASK_CUSTOMER,
PROPOSE, ESCALATE — and ``docs/agent-spec.md:22`` fixes the refusals: 未知动作、身份字段、任意URL或写工具拒绝.

**Why the refusal lives here rather than in the tool server.** The MCP server publishes exactly five tools
(``docs/agent-spec.md:26-32``) and validates their arguments, so a caller cannot invoke a sixth. That is a
statement about what a *client* can call. This module is a statement about what the *run* will ask for, and the
two are not the same claim: a harness that forwarded whatever action the model produced and relied on the
server to reject it would be trusting a deployment detail for a permission decision. Both checks exist and
neither is redundant — the server's is the boundary, this one is the policy.

**Why unknown members are forbidden rather than ignored.** ``ModelDecision`` is strict. The three refusals of
``docs/agent-spec.md:22`` that are not about the *kind* — identity fields, arbitrary URLs, write tools — all
arrive as unexpected members or unexpected tool names, so "ignore what you do not recognise" would silently
accept every one of them. The model does not get to send ``line_id``; the run was told which line it is about
(C06.1), and an action that names another one is an attempt to investigate someone else's order.

**Why ``URL_MEMBERS`` is checked by name as well as by shape.** ``source_ref`` is a controlled
``namespace:rest`` reference and never a requestable address (``docs/core-contracts.md:61``). A member named
``url``/``uri``/``endpoint``/``host`` has no meaning in this ABI at all, so it is refused whether or not its
value looks like one — a value check alone would accept ``{"url": "internal-thing"}`` and leave the door open
for the next person who thinks a relative URL is fine.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from resolveflow.contracts.core_models import CoreEvidenceRef, CorePolicyRef, ReviewerFinding, validate_finding_sources
from resolveflow.contracts.enums import CaseType

__all__ = [
    "ASK_CUSTOMER",
    "ESCALATE",
    "MAX_ASK_QUESTIONS",
    "MAX_POLICY_TOP_K",
    "OBSERVATION_READ_TOOL_NAME",
    "POLICY_SEARCH_TOOL_NAME",
    "PROPOSE",
    "READ_OBSERVATION",
    "READ_TOOL",
    "RECOMMENDED_ACTIONS",
    "SEARCH_POLICY",
    "TERMINAL_KINDS",
    "WRITE_TOOL_NAMES",
    "WHITELIST",
    "ActionRefusedError",
    "ModelDecision",
    "validate_decision",
]

#: ``docs/agent-spec.md:2``, the outer vocabulary. These are the only kinds a model may produce.
READ_TOOL: Final = "READ_TOOL"
SEARCH_POLICY: Final = "SEARCH_POLICY"
READ_OBSERVATION: Final = "READ_OBSERVATION"
ASK_CUSTOMER: Final = "ASK_CUSTOMER"
PROPOSE: Final = "PROPOSE"
ESCALATE: Final = "ESCALATE"

#: The kinds that end the run. A decision, not another turn: the loop stops here
#: (``docs/agent-harness.md:25`` — PROPOSE 通过验证后持久最终方案与callback_outbox).
TERMINAL_KINDS: Final[frozenset[str]] = frozenset({PROPOSE, ASK_CUSTOMER, ESCALATE})

#: ``docs/agent-spec.md:18``: 最多3个聚合问题. ``docs/agent-spec.md:16``: top_k<=5.
MAX_ASK_QUESTIONS: Final = 3
MAX_POLICY_TOP_K: Final = 5

#: The case types the contract declares (``contracts/core/agent-proposal.schema.json``, ``openapi-case.yaml``
#: ``CaseType``). A PROPOSE must name one, and one of **these** — the run classifies the case; it does not invent a
#: category the case service would then refuse as a structural error (``docs/core-contracts.md:64``).
CASE_TYPES: Final[frozenset[str]] = frozenset(member.value for member in CaseType)

#: The name the SDK sees for a policy search (C07.1). A **local** capability, not one of the five MCP tools
#: (``docs/agent-spec.md:34``: 政策检索和READ_OBSERVATION是本地能力，不包装成额外微服务), which is why it is not in
#: :data:`WHITELIST` and why the tool server has never heard of it.
#:
#: It lives in the ABI rather than in the runner because two modules need to agree on it — the adapter renders the
#: tool call and the gate decides whether to allow it — and a constant two modules each spell is a constant that
#: will eventually be spelled differently in one of them.
POLICY_SEARCH_TOOL_NAME: Final = "search_policy"

#: The same, for reading back an observation's original text (C07.2's executor).
OBSERVATION_READ_TOOL_NAME: Final = "read_observation"

#: ``docs/agent-spec.md:19``. The harness fills in the identity; the model chooses the action.
RECOMMENDED_ACTIONS: Final[frozenset[str]] = frozenset(
    {"REFUND", "REQUEST_INFO", "MANUAL_REVIEW", "REJECT"}
)

#: The five read-only tools of ``docs/agent-spec.md:26-32``, written out rather than imported from the MCP
#: server: this is the run's policy, and reading it from the thing being policed would let a sixth tool appear
#: in both places at once.
WHITELIST: Final[frozenset[str]] = frozenset(
    {
        "get_order_context",
        "get_shipment_trace",
        "get_refund_status",
        "get_case_evidence",
        "get_policy_manifest",
    }
)

#: Names a tool must never be able to call. Stated as a list rather than inferred from the whitelist, because
#: "not in the whitelist" and "this is a refund" are different sentences in a refusal message, and the second
#: one is the one an operator needs to see.
WRITE_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "issue_refund",
        "request_refund",
        "execute_refund",
        "approve",
        "approve_case",
        "cancel_case",
        "update_policy",
        "modify_policy",
        "write_evidence",
    }
)

#: Member names that would name a requestable address. Refused by name, not only by value (see the module
#: docstring): the ABI has no member that means "go and fetch this", so a member that looks like one is a
#: mistake at best.
URL_MEMBERS: Final[frozenset[str]] = frozenset({"url", "uri", "endpoint", "host", "hostname", "base_url", "href"})

#: The run's own subject. The model cannot supply any of these: they come from the dispatch
#: (``docs/core-scope.md`` — 模型不得指定身份).
IDENTITY_MEMBERS: Final[frozenset[str]] = frozenset(
    {
        "run_id",
        "case_id",
        "input_revision",
        "revision",
        "line_id",
        "order_id",
        "merchant_id",
        "buyer_id",
        "tenant",
        "tenant_id",
        "principal",
        "subject",
        "authorization",
        "credentials",
        "credential",
        "token",
    }
)


class ActionRefusedError(Exception):
    """An action the harness will not execute. Carries the reason code the outcome reports.

    A raised refusal rather than a sanitised decision: the action was not adjusted into something allowed. A
    harness that dropped ``line_id`` and ran the read anyway would have investigated a subject the model chose
    while telling the record it was the run's.
    """

    #: The stable code the run outcome reports (``docs/agent-harness.md:45`` wants a stable reason_code).
    reason_code = "ACTION_REFUSED"

    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        if reason_code is not None:
            self.reason_code = reason_code


class AskQuestion(BaseModel):
    """One aggregated question (``docs/agent-spec.md:18``).

    ``question_id`` is stable so a new revision can inherit the问答 without the customer's answer having to be
    matched to a sentence (``docs/agent-spec.md:9``).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    question_id: Annotated[str, Field(min_length=1, max_length=64)]
    prompt: Annotated[str, Field(min_length=1, max_length=500)]
    #: Which member of the line the question is about. The case contract's own ``AgentQuestion`` requires ``field``
    #: (`contracts/core/openapi-case.yaml:2146`), and it is the case service that has to route the answer back to
    #: the right part of the case, so the run has to say which part it is asking about rather than leave it implied.
    #:
    #: **Required**: the case contract's ``AgentQuestion`` requires it (``additionalProperties: false`` is what makes a
    #: missing member a refusal rather than a gap), and a question the case service cannot route an answer to is not a
    #: question it can ask.
    field: Annotated[str, Field(min_length=1, max_length=64)]


class ModelDecision(BaseModel):
    """One validated action from the model.

    ``extra="forbid"`` is load-bearing: it is what turns "the model sent a ``line_id``" into a refusal instead
    of a member nobody reads. ``arguments`` is a free-form object only because the five tools have three
    different argument shapes; the whitelist check keeps it from being free-form in effect.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    #: The one-line of reasoning the trajectory keeps (``docs/agent-spec.md:52`` — only explicit action, short
    #: reason, input snapshot and tool results; never hidden chain of thought).
    reasoning: Annotated[str, Field(max_length=1000)] = ""
    reason_codes: Annotated[list[str], Field(max_length=16)] = []

    kind: str
    tool_name: str | None = None
    arguments: dict[str, Any] = {}
    cursor: str | None = None
    query: str | None = None
    observation_id: str | None = None
    questions: list[AskQuestion] = []
    recommended_action: str | None = None
    #: What the run decided the case *is*. The case contract is explicit that this is the run's own classification
    #: (`contracts/core/openapi-case.yaml:1700-1706`: "the run classified the case and named its codes"), and
    #: `ProposalPayload` requires it — so a proposal without one is not a proposal the case service accepts.
    #: It classifies; it does **not** route: `docs/agent-harness.md:9` keeps the action path driven by the
    #: observations, not by a case type.
    #:
    #: **Required on a PROPOSE**: every PROPOSE fixture and every model reply must name one, because
    #: ``ProposalPayload`` requires it and a proposal the case service refuses structurally is not a proposal. A value
    #: that is present is checked against the contract's own four, so the member cannot be used to invent a category.
    case_type: str | None = None
    summary: Annotated[str, Field(max_length=2000)] | None = None
    #: What the proposal cites (C08.1c). The reference shapes are the contract's own types rather than copies, so a
    #: citation cannot satisfy a laxer local shape than Java will enforce — ``CoreEvidenceRef`` refuses a URL as a
    #: ``source_ref`` and a short hash, which is what makes "must be visible" checkable at all.
    #:
    #: Only a PROPOSE may carry these. Before C08.1c nothing could: ``extra="forbid"`` refused the members, so a
    #: refund proposal had no citations to verify and the proposal verifier would have had nothing to check.
    evidence_refs: list[CoreEvidenceRef] = []
    policy_refs: list[CorePolicyRef] = []
    missing_evidence: Annotated[list[str], Field(max_length=10)] = []
    review_findings: Annotated[list[ReviewerFinding], Field(max_length=8)] = []

    @model_validator(mode="after")
    def check_kind_and_its_members(self) -> ModelDecision:
        """Each kind carries exactly the members it needs, and no member of a kind it is not.

        A ``READ_TOOL`` carrying ``recommended_action`` is not a harmless extra: it is a decision smuggled in
        through a read, and the run would execute a refund-shaped action without the proposal path's checks.
        """
        if self.kind not in {READ_TOOL, SEARCH_POLICY, READ_OBSERVATION, ASK_CUSTOMER, PROPOSE, ESCALATE}:
            raise ValueError(f"{self.kind!r} is not one of the six action kinds of docs/agent-spec.md:2")
        if self.kind not in TERMINAL_KINDS and self.recommended_action is not None:
            raise ValueError(f"a {self.kind} action may not carry a recommended_action; that is a PROPOSE")
        if self.kind == PROPOSE and self.recommended_action is None:
            raise ValueError("a PROPOSE must name a recommended_action")
        if self.kind == PROPOSE and not self.reason_codes:
            raise ValueError("a PROPOSE must carry at least one reason code")
        if self.kind == PROPOSE and self.case_type is None:
            raise ValueError(
                "a PROPOSE must classify the case: ProposalPayload requires case_type and the run is who "
                "classified it (contracts/core/openapi-case.yaml:1622)"
            )
        if self.case_type is not None and self.case_type not in CASE_TYPES:
            raise ValueError(
                f"{self.case_type!r} is not one of the contract's case types {sorted(CASE_TYPES)}; "
                "the run classifies the case, it does not invent a category"
            )
        if self.kind != PROPOSE and self.case_type is not None:
            raise ValueError(f"a {self.kind} action may not carry a case_type; that is a PROPOSE")
        if self.kind != ASK_CUSTOMER and self.questions:
            raise ValueError(f"a {self.kind} action may not carry questions")
        # Citations belong to the proposal, and only to it. A read that carries one is a proposal smuggled through a
        # read — the same mistake ``recommended_action`` above is refused for — and an ESCALATE must not invent
        # citations it did not gather (docs/agent-spec.md:20).
        if self.kind != PROPOSE and (
            self.evidence_refs or self.policy_refs or self.missing_evidence or self.review_findings
        ):
            raise ValueError(f"a {self.kind} action may not carry citations; that is a PROPOSE")
        validate_finding_sources(self.review_findings, self.evidence_refs)
        return self


def validate_decision(raw: dict[str, Any]) -> ModelDecision:
    """Validate one model reply, or raise :class:`ActionRefusedError` saying which rule refused it.

    Two stages, deliberately: the model's own shape, then the harness's policy. Reporting both through one
    exception type is what lets the runner treat "the model sent PROPOSE with no action" and "the model asked
    for a tool that does not exist" the same way — the run stops and the reason is recorded — without losing
    which one happened, because the message says.
    """
    try:
        decision = ModelDecision.model_validate(raw)
    except ValidationError as refusal:
        finding_detail = _finding_source_detail(raw)
        if finding_detail:
            raise ActionRefusedError(finding_detail, reason_code="FINDING_SOURCE_INVALID") from refusal
        # A repair needs field names and constraints, not Pydantic's echoed model payload.
        # Keep the mandatory repair notice bounded so a large proposal cannot crowd it out.
        details = "; ".join(
            (".".join(str(part) for part in error["loc"]) + ": " + error["msg"])[:160]
            for error in refusal.errors(include_input=False, include_url=False)[:4]
        )
        raise ActionRefusedError(f"the model's action is not one this ABI accepts: {details}") from refusal
    except Exception as refusal:
        raise ActionRefusedError(f"the model's action is not one this ABI accepts: {refusal}") from refusal

    if decision.kind == READ_TOOL:
        _check_tool(decision)
    if decision.kind == ASK_CUSTOMER:
        _check_questions(decision)
    if decision.kind == SEARCH_POLICY:
        _check_policy_search(decision)
    if decision.kind == PROPOSE:
        if decision.recommended_action not in RECOMMENDED_ACTIONS:
            raise ActionRefusedError(
                f"{decision.recommended_action!r} is not a core proposal action; "
                f"docs/agent-spec.md:19 allows {sorted(RECOMMENDED_ACTIONS)}"
            )
        _check_arguments(decision.arguments, what="a PROPOSE")
        gap_error = request_info_gap_error(decision.recommended_action, decision.missing_evidence)
        if gap_error:
            raise ActionRefusedError(gap_error, reason_code="REQUEST_INFO_INCOMPLETE")
    if decision.kind == ESCALATE and decision.recommended_action is not None:
        # ESCALATE produces a MANUAL_REVIEW proposal or a failure callback and never invents a citation
        # (docs/agent-spec.md:20). The action it recommends is therefore fixed here rather than chosen.
        raise ActionRefusedError("an ESCALATE does not choose its own recommended action")
    return decision


def _finding_source_detail(raw: dict[str, Any]) -> str:
    """Explain a failed strict validation; never repair the model's references automatically."""
    findings, refs = raw.get("review_findings"), raw.get("evidence_refs")
    if not isinstance(findings, list) or not isinstance(refs, list):
        return ""
    available = {ref.get("observation_id") for ref in refs if isinstance(ref, dict)
                 and isinstance(ref.get("observation_id"), str)}
    for index, finding in enumerate(findings[:8]):
        if not isinstance(finding, dict):
            continue
        ids = finding.get("observation_ids")
        if (not isinstance(ids, list) or not ids or len(ids) > 8
                or any(not isinstance(value, str) or not 1 <= len(value) <= 64 for value in ids)):
            continue
        path = f"review_findings.{index}.observation_ids"
        if finding.get("kind") == "CONFLICT" and len(set(ids)) < 2:
            return (f"{path}: CONFLICT has {len(set(ids))} distinct source(s); needs >=2 actual disagreeing "
                    "observations also in evidence_refs. Do not add unrelated sources; "
                    "correct/drop unsupported finding.")
        if len(set(ids)) != len(ids):
            return f"{path}: source IDs must be unique; remove duplicates, do not invent another source."
        missing = sorted(set(ids) - available)
        if missing:
            names = ','.join(repr(value) for value in missing)
            return (f"{path}: {names} absent from evidence_refs. Cite the actual supporting P2 evidence "
                    "in evidence_refs or correct/drop this finding; do not add unrelated sources.")
    return ""


def request_info_gap_error(action: str | None, missing: list[str] | tuple[str, ...]) -> str:
    if action == "REQUEST_INFO" and (not missing or any(not value.strip() for value in missing)):
        return ("missing_evidence: REQUEST_INFO needs explicit nonblank customer-provided material gaps; "
                "system/merchant checks require investigation or human handover. "
                "PROPOSE does not send a customer question.")
    return ""


def _check_tool(decision: ModelDecision) -> None:
    name = decision.tool_name
    if not name:
        raise ActionRefusedError("a READ_TOOL must name a tool")
    if name in WRITE_TOOL_NAMES:
        raise ActionRefusedError(
            f"{name!r} writes; the Agent has no write tools at all (docs/agent-spec.md:22, docs/core-scope.md)",
            reason_code="WRITE_TOOL_REFUSED",
        )
    if name not in WHITELIST:
        raise ActionRefusedError(
            f"{name!r} is not one of the five whitelisted tools (docs/agent-spec.md:26-32)",
            reason_code="UNKNOWN_TOOL",
        )
    _check_arguments(decision.arguments, what=f"a {name} call")


def _check_arguments(arguments: dict[str, Any], *, what: str) -> None:
    """Refuse identity members, requestable addresses, and nested versions of either.

    Recursive, because ``{"arguments": {"source": {"url": ...}}}`` is the same mistake one level down, and a
    shallow check would accept it.
    """
    _walk(arguments, what=what, depth=0)


def _walk(node: Any, *, what: str, depth: int) -> None:
    if depth > 8:
        raise ActionRefusedError(f"{what} nests deeper than any tool argument should")
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if lowered in URL_MEMBERS:
                raise ActionRefusedError(
                    f"{what} names a requestable address ({key!r}); a source is a controlled reference, "
                    "never a URL (docs/core-contracts.md:61)",
                    reason_code="ARBITRARY_URL_REFUSED",
                )
            if lowered in IDENTITY_MEMBERS:
                raise ActionRefusedError(
                    f"{what} names {key!r}, which is the run's own subject and not the model's to supply "
                    "(docs/core-scope.md)",
                    reason_code="IDENTITY_REFUSED",
                )
            if isinstance(value, str) and "://" in value:
                raise ActionRefusedError(
                    f"{what} carries a requestable address in {key!r}: {value[:60]!r}",
                    reason_code="ARBITRARY_URL_REFUSED",
                )
            _walk(value, what=what, depth=depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk(item, what=what, depth=depth + 1)


def _check_questions(decision: ModelDecision) -> None:
    if not decision.questions:
        raise ActionRefusedError("an ASK_CUSTOMER must carry at least one question")
    if len(decision.questions) > MAX_ASK_QUESTIONS:
        raise ActionRefusedError(
            f"an ASK_CUSTOMER carries at most {MAX_ASK_QUESTIONS} aggregated questions "
            f"(docs/agent-spec.md:18); this one carries {len(decision.questions)}"
        )
    ids = [question.question_id for question in decision.questions]
    if len(set(ids)) != len(ids):
        raise ActionRefusedError("question ids must be distinct, or an answer cannot name which one it answers")
    system_fields = {"fulfillment_status", "fulfillment_version", "order_status", "payment_status",
                     "line_paid_amount", "order_paid_amount", "line_refund_state", "refunded_amount",
                     "reserved_refund_amount", "carrier_conclusion", "verification_result"}
    for index, question in enumerate(decision.questions):
        if question.field.strip().lower().rsplit(".", 1)[-1] in system_fields:
            raise ActionRefusedError(
                f"questions.{index}.field={question.field}: authoritative system/merchant fact; use the bound "
                "read tools or human verification, not customer evidence. Ask only customer-provided materials.",
                reason_code="QUESTION_RESPONSIBILITY_INVALID")


def _check_policy_search(decision: ModelDecision) -> None:
    if not decision.query:
        raise ActionRefusedError("a SEARCH_POLICY must carry a query")
    top_k = decision.arguments.get("top_k")
    if top_k is not None:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1 or top_k > MAX_POLICY_TOP_K:
            raise ActionRefusedError(f"a SEARCH_POLICY takes top_k at most {MAX_POLICY_TOP_K}")
    _check_arguments(decision.arguments, what="a SEARCH_POLICY")


#: The literal type of a decision kind, exported for a reader who wants the ABI in one place.
DecisionKind = Literal[
    "READ_TOOL", "SEARCH_POLICY", "READ_OBSERVATION", "ASK_CUSTOMER", "PROPOSE", "ESCALATE"
]
