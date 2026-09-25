"""Which fields a run takes from an observation, and how the layers are assembled (C07.2).

Two things live here, and they are separate concerns that share a module because the second one is the only
reader of the first.

**Extraction** turns a ``ToolObservation`` into ``(key, value)`` facts. It is a *fixed* mapping per tool, not a
walk over whatever JSON arrived, and that is deliberate: ``docs/context-engineering.md:19`` forbids rewriting
prose into fields and ``:23`` forbids letting the evaluation's gold data decide what is relevant. A permissive
extractor that took every scalar it found would put a carrier's free-text remark into P2 beside the paid amount,
and the model could not tell which of them a refund is checked against. So each tool has a named field list,
written once, and a key the tool does not carry simply produces no fact.

**Assembly** puts the layers together under the input cap. The cap is
``min(8192, provider capacity − output reserve − 256, cumulative input remaining)`` (``:27``), and the order the
layers go in is the specification's, with one consequence that is the whole reason this is not a sorting
function: **P0 is never trimmed**, so if P0 plus P1 plus P2 do not fit, the run does not get a shorter
constraint list — it gets ``CONTEXT_REQUIRED_OVERFLOW`` and a human (``:27`` 转索引后仍超限则
CONTEXT_REQUIRED_OVERFLOW转人工，不删约束).

**P2 facts are rendered as text, not as prose.** Each line is ``key=value`` plus its source and status, so the
model sees the *field* rather than a sentence about the field; a conflict appears as both facts with
``status=CONFLICT``, because ``:11`` requires both to survive and a builder that picked one would be deciding the
case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.facts import Fact, FactStatus, FactsView, facts_hash

__all__ = [
    "CONTEXT_REQUIRED_OVERFLOW",
    "DEFAULT_INPUT_CAP",
    "DEFAULT_OUTPUT_RESERVE",
    "MAX_EXCERPT_CHARS",
    "PROVIDER_WRAPPER_ALLOWANCE",
    "ContextBuilder",
    "ContextPacket",
    "Layer",
    "OverflowRefusedError",
    "estimate_tokens",
    "extract_facts",
]

#: ``docs/context-engineering.md:27``: the absolute ceiling for one request's input.
DEFAULT_INPUT_CAP: Final = 8192

#: What is held back for the answer. ``docs/agent-spec.md:40`` fixes the per-step output ceiling at 1024, and
#: ``docs/context-engineering.md:27`` names "输出预留" as a term in the cap, so this is that term — not a second
#: copy of the per-step cap, which the budget already enforces as a ceiling on the request itself.
DEFAULT_OUTPUT_RESERVE: Final = 1024

#: ``docs/context-engineering.md:27``: 计入system/tool schema/provider包装. A fixed allowance for the framing a
#: provider adds around the messages (role markers, separators, the tool-choice envelope). It is an allowance
#: rather than a measurement because no provider publishes an exact figure, and the direction it errs in is the
#: safe one: reserving 256 tokens that are not used means refusing a request that might have fitted, while
#: assuming zero means sending one that does not.
PROVIDER_WRAPPER_ALLOWANCE: Final = 256

#: ``docs/agent-spec.md:36``: 给模型的excerpt<=8KiB. Counted in characters here because that is the unit the tool
#: layer truncates in; the token estimate is applied afterwards.
MAX_EXCERPT_CHARS: Final = 8 * 1024

#: How many of the most recent observations P3 carries **with their content**; the rest become P4 index entries.
#:
#: Two, because the layers answer one question — "what is the run working from right now" — and the tool loop
#: allows 1-3 reads per step (``docs/agent-spec.md:15``), so the current step's evidence plus the one before it is
#: what a decision is made from. A larger window pushes the index out of the budget; a smaller one puts the step's
#: own evidence behind a read (``READ_OBSERVATION``) the model would have to know to make.
OBSERVATION_WINDOW: Final = 2

#: The reason code ``docs/context-engineering.md:27`` names for "even after indexing, this does not fit".
CONTEXT_REQUIRED_OVERFLOW: Final = "CONTEXT_REQUIRED_OVERFLOW"


class OverflowRefusedError(RuntimeError):
    """The mandatory layers do not fit, so the run stops instead of losing a constraint.

    Carries :attr:`reason_code` so the loop reports the code the specification names, and the numbers, because
    "does not fit" without them leaves an operator unable to tell a huge P1 from a too-small cap.
    """

    reason_code = CONTEXT_REQUIRED_OVERFLOW

    def __init__(self, message: str, *, mandatory_tokens: int, cap: int) -> None:
        super().__init__(message)
        self.mandatory_tokens = mandatory_tokens
        self.cap = cap


class Layer:
    """The five layers of ``docs/context-engineering.md:17-21``, in assembly order.

    A plain class rather than an enum because the names carry the meaning and nothing iterates them by rank; the
    module's constants are the layer *labels* a packet uses.
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


#: Which layers may be trimmed when the request does not fit. P0 is absent from this set, and that is the
#: specification's 不可裁剪 written as data rather than as a comment in the trim branch.
TRIMMABLE_LAYERS: Final[frozenset[str]] = frozenset({Layer.P3, Layer.P4})


def estimate_tokens(text: str) -> int:
    """A conservative token estimate: characters over three, minimum one.

    Over three rather than the four the budget hook uses, and the difference is deliberate: Chinese text is
    roughly one token per character to one per two, so four-characters-per-token would *under*-count exactly the
    corpus this project has, and under-counting is the direction that lets an over-long request through. The
    estimate is still an estimate, which is why a packet records ``token_count_mode``.
    """
    if not text:
        return 0
    return max(1, len(text) // 3)


#: The fields each tool contributes to P2, with the JSON path they live at in ``observation.result``.
#:
#: Written out per tool rather than discovered, for the reason in this module's docstring: what belongs in P2 is
#: a decision about what a refund is checked against, and a generic extractor would make it an accident of what
#: a service happened to return. A path that is absent yields no fact — which is a real state (a tool that
#: could not observe) and not an error.
EXTRACTED_FIELDS: Final[dict[str, dict[str, str]]] = {
    "get_order_context": {
        "order_paid_amount_minor": "line_paid_amount",
        "order_currency": "currency",
        "order_paid_at": "paid_at",
        "order_quantity": "quantity",
        "order_status": "status",
    },
    "get_refund_status": {
        "line_refunded_amount_minor": "refunded_amount",
        "line_reserved_amount_minor": "reserved_amount",
        "line_refundable_amount_minor": "refundable_amount",
        "line_refund_state": "state",
    },
    "get_shipment_trace": {
        "shipment_carrier_conclusion": "carrier_conclusion",
        "shipment_status": "status",
        "shipment_last_scan_at": "last_scan_at",
        "shipment_scan_count": "scan_count",
    },
    "get_case_evidence": {
        "evidence_kind": "kind",
        "evidence_count": "count",
    },
    "get_policy_manifest": {
        "policy_manifest_hash": "manifest_hash",
        "policy_bundle_id": "bundle_id",
        "policy_version": "version",
    },
    "search_policy": {
        # The top hit only, and by identity: P2 records *which rule* the run is working from, while the rule's
        # text is prose and belongs in P3 with its citation (a whole rule is up to 4000 characters).
        "policy_top_rule_id": "top_rule_id",
        "policy_top_chunk_id": "top_chunk_id",
        "policy_top_content_hash": "top_content_hash",
    },
}


def _scalar(value: Any) -> str | None:
    """One JSON value as a fact value, or ``None`` if it is not a scalar.

    Nested objects and lists are skipped rather than serialised: a JSON blob in a fact value is a summary in
    disguise, and the exact fields it contains would then be unreadable to whatever checks the fact later.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return None
    if isinstance(value, str):
        return value or None
    return None


def extract_facts(view: FactsView, observation: ToolObservation) -> list[Fact]:
    """Record every configured field of ``observation`` into ``view``; return the facts it contributed.

    A failed observation contributes nothing and is not an error: ``docs/agent-spec.md:36`` makes NOT_FOUND a
    read that happened, and a read that observed nothing has no fields to report. What it does have is an
    ``error``, and the caller decides whether the *absence* is itself a fact (it usually is, and the loop records
    it in P3 as a gap).
    """
    if observation.error is not None:
        return []
    result = observation.result
    if not isinstance(result, dict):
        return []
    fields = EXTRACTED_FIELDS.get(observation.tool_name)
    if not fields:
        return []

    contributed: list[Fact] = []
    for key, path in fields.items():
        value = _scalar(result.get(path))
        if value is None:
            continue
        contributed.append(view.note(key=key, value=value, observation=observation))
    return contributed


@dataclass(frozen=True, slots=True)
class ContextPacket:
    """What one model request actually carried, and the hashes that let a reader check the claim.

    ``messages`` is the assembled input as the provider would see it (a list of ``{role, content}`` mappings),
    not a summary of one: ``docs/context-engineering.md:37`` requires the **final** request to be hashed rather
    than a pre-adaptation approximation, and the only way to keep that promise is to keep the bytes.

    ``omitted_refs`` names what was dropped and why — a trim that records only that it trimmed leaves a reviewer
    unable to tell a dropped duplicate from a dropped contradiction.
    """

    context_id: str
    run_id: str
    step: int
    manifest_id: str
    messages: tuple[dict[str, str], ...]
    tool_schema_hash: str
    token_count_mode: str
    input_tokens: int
    input_cap: int
    selected_refs: tuple[str, ...]
    omitted_refs: tuple[dict[str, str], ...]
    protected_fact_hash: str
    context_hash: str
    facts: tuple[dict[str, Any], ...] = ()
    #: Layers that were present before trimming, so a reader can see that P4 was dropped rather than never built.
    layers: tuple[str, ...] = field(default=())

    @property
    def as_messages(self) -> list[dict[str, str]]:
        return [dict(message) for message in self.messages]


@dataclass(slots=True)
class _Section:
    """One rendered piece of the input, with the layer it belongs to.

    Kept as a list of sections rather than one string so trimming happens *between* pieces: cutting a rendered
    blob by character count is how half a constraint gets sent, and ``docs/context-engineering.md:27``'s
    不删约束 has to mean "drop whole sections, never letters".
    """

    layer: str
    label: str
    text: str
    #: A reference a reader can follow back to the source, for the refs lists.
    ref: str | None = None

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass(slots=True)
class ContextBuilder:
    """Assembles one request from the run's facts, observations and pins, under the input cap.

    Owned per run, like the budget and the no-progress tracker, and for the same reason: what a model may be
    shown depends on what *this* run has learned, and a builder shared between runs would let one run's evidence
    appear in another's prompt.

    The builder does not call the model and does not decide anything. It renders, measures, and either returns a
    packet or refuses with ``CONTEXT_REQUIRED_OVERFLOW``.
    """

    system_prompt: str
    #: ``docs/agent-spec.md:40``'s per-step input ceiling is *not* passed in: the cap is computed from the three
    #: terms ``docs/context-engineering.md:27`` names, and taking a fourth from a caller is how one of them stops
    #: being applied. ``cumulative_remaining`` is the third term and does come from the budget, because only the
    #: budget knows what the run has already spent.
    provider_capacity: int = DEFAULT_INPUT_CAP
    output_reserve: int = DEFAULT_OUTPUT_RESERVE
    provider_wrapper_allowance: int = PROVIDER_WRAPPER_ALLOWANCE
    #: Recorded in the packet. ``ESTIMATED`` unless a caller has a provider's real tokeniser, which this project
    #: does not — ``docs/agent-spec.md:44`` allows the estimate as long as it is *marked*.
    #:
    #: ``noqa: S105`` because the rule reads the assignment of a string literal to a name containing "token" as a
    #: credential. This member is the *label* for how the count was produced, and renaming it to dodge the rule
    #: would put a less accurate name in a snapshot a reader has to interpret.
    token_count_mode: str = "ESTIMATED"  # noqa: S105

    def input_cap(self, *, cumulative_remaining: int | None = None) -> int:
        """``min(8192, provider容量-输出预留-256, 累计剩余输入)`` — the three terms, in one place.

        A negative or zero result is clamped to zero rather than passed on: the packet's ``input_cap`` is read by
        a report, and a negative cap would print as a budget that owes the run tokens.
        """
        terms = [
            DEFAULT_INPUT_CAP,
            self.provider_capacity - self.output_reserve - self.provider_wrapper_allowance,
        ]
        if cumulative_remaining is not None:
            terms.append(cumulative_remaining)
        return max(0, min(terms))

    def build(
        self,
        *,
        run_id: str,
        case_id: str,
        step: int,
        input_revision: int,
        line_id: str,
        description: str,
        manifest_id: str,
        view: FactsView,
        observations: list[ToolObservation],
        tool_schema: dict[str, Any],
        cumulative_remaining: int | None = None,
        history: list[dict[str, str]] | None = None,
        now: str | None = None,
    ) -> ContextPacket:
        """Build the packet, or raise :class:`OverflowRefusedError` naming what did not fit.

        ``history`` is the previous turns' questions and answers, which ``docs/context-engineering.md:19`` puts in
        P1. It arrives already rendered (the loop owns the conversation) and is trimmed from the **oldest** end
        when P1 does not fit, because the most recent exchange is what the current question depends on.
        """
        cap = self.input_cap(cumulative_remaining=cumulative_remaining)
        sections: list[_Section] = []
        omitted: list[dict[str, str]] = []

        # P0 — the system prompt and the action/tool schema. Never trimmed: 不可裁剪.
        sections.append(_Section(layer=Layer.P0, label="system", text=self.system_prompt))
        sections.append(
            _Section(layer=Layer.P0, label="tool_schema", text=_render_tool_schema(tool_schema))
        )

        # P1 — the request itself and what has already been asked and answered.
        sections.append(
            _Section(
                layer=Layer.P1,
                label="request",
                text=(
                    f"当前诉求：{description}\n"
                    f"run={run_id} case={case_id} revision={input_revision} line={line_id}"
                ),
            )
        )
        for index, turn in enumerate(history or []):
            sections.append(
                _Section(
                    layer=Layer.P1,
                    label=f"turn_{index}",
                    text=f"[{turn.get('role', 'user')}] {turn.get('content', '')}",
                    ref=f"turn:{index}",
                )
            )

        # P2 — the exact fields a decision is checked against, each with its source and status.
        for line in _render_facts(view):
            sections.append(_Section(layer=Layer.P2, label="fact", text=line))

        # P3 — the current observations, bounded and cited; P4 — everything earlier, identity only.
        #
        # The split is what keeps the two layers from being the same thing twice. The first version put *every*
        # observation in both (P3 with content, P4 as an index sharing the same ``ref``), and P4 was then deleted
        # wholesale by the duplicate rule — so the index that exists to make prose reachable was never sent. The
        # specification's own words separate them: P3 is 当前Observation, P4 is 较早工具/问答索引
        # (docs/context-engineering.md:19-21).
        #
        # Duplicates are removed **here, before rendering**, and that order is load-bearing: dropping rendered
        # sections kept whichever copy came last while the surviving section still claimed the *first* copy's
        # observation id, so the message carried one read's content under another read's reference. A message that
        # misattributes evidence is worse than a duplicate, and a test asserting the kept content caught it.
        unique, duplicates = _unique_observations(observations)
        omitted.extend(duplicates)
        recent = unique[-OBSERVATION_WINDOW:] if unique else []
        earlier = unique[: max(0, len(unique) - OBSERVATION_WINDOW)]
        sections.extend(_observation_sections(recent))
        sections.extend(_index_sections(earlier))

        mandatory = [section for section in sections if section.layer not in TRIMMABLE_LAYERS]
        optional = [section for section in sections if section.layer in TRIMMABLE_LAYERS]

        mandatory_tokens = sum(section.tokens for section in mandatory) + self._framing_tokens
        if mandatory_tokens > cap:
            # 转索引后仍超限 → 转人工 (docs/context-engineering.md:27). P0/P1/P2 are exactly the layers that may
            # not be dropped, so there is nothing left to index: the honest outcome is a refusal a human reads,
            # and the message says which layer is large so the fix is findable.
            raise OverflowRefusedError(
                f"the request does not fit: P0+P1+P2 need about {mandatory_tokens} tokens and the cap is {cap}. "
                f"P0 is never trimmed, so this run stops with {CONTEXT_REQUIRED_OVERFLOW} rather than dropping a "
                f"constraint. Largest layer: {max(mandatory, key=lambda item: item.tokens).layer}"
                f"/{max(mandatory, key=lambda item: item.tokens).label}.",
                mandatory_tokens=mandatory_tokens,
                cap=cap,
            )

        kept = list(mandatory)
        remaining = cap - mandatory_tokens
        # **Oldest first** within the trimmable layers, and content before index.
        #
        # The first version dropped whole layers, so P4 was all-or-nothing: a cap that could not fit every index
        # entry threw the entire index away, including the entries for the two observations just before the
        # window — the ones ``READ_OBSERVATION`` is most likely to be asked about. ``docs/context-engineering.md:27``
        # says 去重复和**最旧**非关键段, which is a per-segment rule: the newest history is the last thing to go.
        # P3 is ordered before P4 because an index entry is useless without the capability to read it back, while a
        # content-bearing excerpt is directly usable.
        for section in _trimmable_oldest_first(optional):
            if section.tokens <= remaining:
                kept.append(section)
                remaining -= section.tokens
            else:
                omitted.append(_omission(section, "would not fit the remaining input budget"))

        # The priority order above decides **what survives**; the layer order decides where it appears. Without
        # this the message would carry P3/P4 entries in trim order, which reads as a shuffled trajectory.
        kept.sort(key=lambda section: (section.layer, section.label))
        messages = self._render(kept)

        selected = tuple(section.ref for section in kept if section.ref)
        protected = facts_hash(view)
        return ContextPacket(
            context_id=_context_id(run_id, step, protected),
            run_id=run_id,
            step=step,
            manifest_id=manifest_id,
            messages=messages,
            tool_schema_hash=_hash_json(tool_schema),
            token_count_mode=self.token_count_mode,
            input_tokens=sum(section.tokens for section in kept) + self._framing_tokens,
            input_cap=cap,
            selected_refs=selected,
            omitted_refs=tuple(omitted),
            protected_fact_hash=protected,
            context_hash=_hash_messages(messages, self.system_prompt),
            facts=tuple(fact.as_dict() for fact in view.live()),
            layers=tuple(sorted({section.layer for section in kept})),
        )

    @property
    def _framing_tokens(self) -> int:
        """The provider wrapper allowance, as tokens, so it is counted rather than mentioned.

        ``docs/context-engineering.md:27`` says the cap is 计入system/tool schema/provider包装, and a term that is
        subtracted from the cap *and* excluded from the total would be counted twice. Only the system prompt and
        the schema are subtracted through their own sections, so the wrapper is added here — once.
        """
        return self.provider_wrapper_allowance

    def _render(self, sections: list[_Section]) -> tuple[dict[str, str], ...]:
        """The sections as provider turns: P0 becomes the system turns, everything else one user turn.

        Several system turns rather than one concatenated string, because ``tool_schema`` is a distinct thing a
        reader may need to see whole; and the layer labels survive inside the text so a reader of a snapshot can
        tell which layer a line came from without a second file.
        """
        system_parts = [section.text for section in sections if section.layer == Layer.P0]
        body = "\n".join(
            f"【{section.layer}·{section.label}】{section.text}"
            for section in sections
            if section.layer != Layer.P0
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": body},
        ]
        return tuple(messages)


def _trimmable_oldest_first(sections: list[_Section]) -> list[_Section]:
    """The trimmable sections in the order they should be **kept**.

    P3 before P4 (content is directly usable, an index entry is not), and inside each layer the later section
    first — the sections were built oldest-first, so reversing preserves the most recent history longest. The
    returned order is a *priority*, not the order they end up in the message; ``_render`` re-sorts by layer, so a
    section kept out of priority order still appears where its layer belongs.
    """
    return [
        section
        for layer in (Layer.P3, Layer.P4)
        for section in reversed([item for item in sections if item.layer == layer])
    ]


def _render_facts(view: FactsView) -> list[str]:
    """P2 as one line per fact, source and status included.

    ``docs/context-engineering.md:19`` forbids a generative rewrite of these fields, so the rendering is
    mechanical: the value the tool returned, the source it came from, and whether it is fresh. A conflict
    therefore reaches the model as two lines that disagree rather than as a resolved sentence, which is the
    point of keeping both.
    """
    lines: list[str] = []
    for fact in view.facts:
        marker = "" if fact.status is FactStatus.FRESH else f" status={fact.status}"
        note = f" ({fact.note})" if fact.note and fact.status is not FactStatus.FRESH else ""
        version = f"@{fact.source_version}" if fact.source_version else ""
        lines.append(f"{fact.key}={fact.value} [{fact.authority} {fact.source_ref}{version}]{marker}{note}")
    return lines


def _unique_observations(
    observations: list[ToolObservation],
) -> tuple[list[ToolObservation], list[dict[str, str]]]:
    """The run's observations with repeats of one id removed, plus the omissions that removal produced.

    The first occurrence wins, because observation order is the run's own order and the first read of an id is the
    one the run actually made; a later arrival under the same id is the same record being handed over twice, and
    keeping it would silently replace the evidence the model was already told about.
    """
    seen: set[str] = set()
    kept: list[ToolObservation] = []
    dropped: list[dict[str, str]] = []
    for observation in observations:
        if observation.observation_id in seen:
            dropped.append(
                {
                    "layer": Layer.P3,
                    "label": f"observation:{observation.tool_name}",
                    "ref": observation.observation_id,
                    "reason": f"duplicate of the earlier entry for {observation.observation_id}",
                }
            )
            continue
        seen.add(observation.observation_id)
        kept.append(observation)
    return kept, dropped


#: How large a single observation field may be before the excerpt replaces it with a pointer to the原文. The
#: bound is per **field**, not per excerpt, so what the model receives stays well-formed data.
MAX_FIELD_CHARS: Final = 2000


def _observation_sections(observations: list[ToolObservation]) -> list[_Section]:
    """P3: the **current** observations, bounded and cited.

    The excerpt bytes are bounded two ways, and the first version of this got the second one wrong:

    1. **Per field**: a field longer than :data:`MAX_FIELD_CHARS` is replaced by a pointer to the observation, which
       is what ``docs/context-engineering.md:29`` means by 用首末/异常/状态变化结构化提取，保留原文位置 — the
       model gets the structure and the location, not a wall of text.
    2. **Per excerpt**, as a last resort at ``docs/agent-spec.md:36``'s 8 KiB.

    The first version bounded only the total and cut it by **character count**, which did two harmful things: it
    produced a JSON fragment that is not valid JSON — the illegal provider shape ``:29`` forbids — and a long
    ``raw`` field early in the object pushed the structured fields *out* of the excerpt entirely, so the model
    would see a truncated blob instead of the conclusion it is deciding from. A fixture with a long tracking
    history and a long raw body is what showed it.
    """
    sections: list[_Section] = []
    for observation in observations:
        rendered = _render_excerpt(observation)
        if len(rendered) > MAX_EXCERPT_CHARS:
            # The last resort, and by now rare: every field is bounded, so reaching this means the *number* of
            # fields is what is large. The pointer still names the observation, so nothing is lost.
            rendered = rendered[:MAX_EXCERPT_CHARS] + f"…（截断，原文见 {observation.observation_id}）"
        sections.append(
            _Section(
                layer=Layer.P3,
                label=f"observation:{observation.tool_name}",
                text=rendered,
                ref=observation.observation_id,
            )
        )
    return sections


def _excerpt_result(observation: ToolObservation) -> Any:
    """The observation's result, with oversized fields replaced by a pointer rather than truncated.

    Only top-level fields are considered, because a whole observation is what the tool layer bounded
    (``docs/agent-spec.md:36``'s 256 KiB) and restructuring a nested payload here would be this module deciding what
    a tool's result means.
    """
    result = observation.result
    if not isinstance(result, dict):
        return result
    bounded: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            offset = _field_offset(observation, key)
            bounded[key] = (
                f"<{len(value)} 字符，已省略；用 READ_OBSERVATION 读 "
                f"{observation.observation_id} 的 offset={offset}>"
            )
        else:
            bounded[key] = value
    return bounded


def _field_offset(observation: ToolObservation, key: str) -> int:
    """Where a field's value starts inside the observation's **readable text**, so the pointer is usable.

    Computed against :func:`_render_observation` — the same string ``READ_OBSERVATION`` serves — and not against the
    bare JSON. The first version searched the JSON and returned the position within *it*, which is short by the
    ``"<tool>: "`` prefix, so a model following the pointer landed a dozen characters early. A pointer the model
    cannot follow is worse than no pointer, and a test that read the offset out of the packet and used it caught
    the discrepancy.
    """
    text = _render_observation(observation)
    marker = f'"{key}":'
    found = text.find(marker)
    # `+1` for the opening quote of the value: the pointer should land **on the value**, so a model that reads one
    # window from it gets the field rather than a stray `"`. The first version landed one character early.
    return found + len(marker) + 1 if found >= 0 else 0


def _index_sections(observations: list[ToolObservation]) -> list[_Section]:
    """P4: identity-only lines for the **earlier** observations, so their prose can be read back on demand.

    This is ``docs/context-engineering.md:21``'s 确定性提取: the run's own record of what it read before the current
    window, in the order it read it, with the reference needed to fetch any of it — and no content, because
    content here is what the trim exists to bound. The numbers are positions in the run's own sequence, so a
    reader can tell the order without a timestamp.
    """
    return [
        _Section(
            layer=Layer.P4,
            label=f"index:{index}",
            text=f"{index}. {observation.tool_name} {observation.observation_id} ({observation.source_ref})",
            # A distinct ref namespace from P3's, because these are *references to* observations rather than the
            # observations themselves: sharing a ref made the duplicate rule treat the index as a second copy of
            # the content and drop it, which is how P4 came to be empty in the first version.
            ref=f"index:{observation.observation_id}",
        )
        for index, observation in enumerate(observations)
    ]


def _render_observation(observation: ToolObservation) -> str:
    """The text of one observation, and the **one** place it is produced.

    ``observation_read`` imports this rather than re-rendering: the packet's P3 excerpt is a prefix of this string,
    so a model that reads a window back and compares it with the excerpt it was shown is looking at one rendering
    of one read. Two renderings that agreed by convention would eventually disagree.
    """
    if observation.error is not None:
        return f"{observation.tool_name} 未能读取：{observation.error.code} {observation.error.message}"
    return f"{observation.tool_name}: {_json(observation.result)}"


def observation_text(observation: ToolObservation) -> str:
    """The public name for the rendering above, for callers outside this module.

    A separate function rather than an underscore export, because the read-back path is a *documented* consumer:
    ``docs/context-engineering.md:21`` makes the index's whole purpose "read it back on demand", and a private name
    would make that consumer look like an accident.
    """
    return _render_observation(observation)


def _render_excerpt(observation: ToolObservation) -> str:
    """The bounded rendering for P3: the same shape, with oversized fields replaced by a pointer.

    Kept beside :func:`_render_observation` because the two must describe the same observation: the excerpt is what
    the model is shown, the full rendering is what it can read back, and the pointer in the excerpt names an offset
    **into the full rendering**.
    """
    if observation.error is not None:
        return _render_observation(observation)
    return f"{observation.tool_name}: {_json(_excerpt_result(observation))}"


def _render_tool_schema(schema: dict[str, Any]) -> str:
    """The action/tool schema, as the model receives it. ``docs/context-engineering.md:17`` makes this P0.

    Sorted keys because the packet's hash covers it: an unstable rendering would make two runs with the same
    schema hash differently, and the hash is what a snapshot uses to say which tools the model was offered.
    """
    return "动作/工具 schema：" + _json(schema)


def _omission(section: _Section, reason: str) -> dict[str, str]:
    return {
        "layer": section.layer,
        "label": section.label,
        "ref": section.ref or "",
        "reason": reason,
    }


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _hash_json(value: Any) -> str:
    import hashlib

    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _hash_messages(messages: tuple[dict[str, str], ...], system_prompt: str) -> str:
    """The hash of the request as assembled, system prompt included.

    ``docs/context-engineering.md:37`` wants the **final** request hashed, so this covers what the provider would
    receive. The honest boundary is stated where it belongs (in the snapshot documentation): the SDK may still add
    its own framing after this, and that gap is recorded as a limitation rather than papered over by hashing the
    conversation object instead.
    """
    import hashlib

    document = {"system": system_prompt, "messages": [dict(message) for message in messages]}
    return hashlib.sha256(_json(document).encode("utf-8")).hexdigest()


def _context_id(run_id: str, step: int, protected_fact_hash: str) -> str:
    """A stable id for one step's context: the same run, step and facts produce the same id.

    Derived rather than random so a retry of the same step is recognisably the same context — ``docs/agent-spec.md:50``
    reuses persisted results by a stable id, and a context id that changed on every attempt could not be part of
    that record.
    """
    import hashlib

    payload = f"{run_id}:{step}:{protected_fact_hash}"
    return "ctx-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

