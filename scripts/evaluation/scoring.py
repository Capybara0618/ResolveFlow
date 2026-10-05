"""Independent scores: valid action plus factual/policy support, never transcript order."""

from __future__ import annotations


def score_agent(result, gold, *, case=None):
    decision = result.decision
    action = getattr(decision, "recommended_action", None)
    if getattr(decision, "kind", None) == "ASK_CUSTOMER":
        action = "REQUEST_INFO"
    elif getattr(decision, "kind", None) == "ESCALATE":
        action = "MANUAL_REVIEW"
    observations = {item.observation_id: item for item in result.observations}
    read_tools = {item.tool_name for item in observations.values() if item.error is None}
    missing_errors = [requirement for requirement in gold.get("must_read_errors", [])
                      if not any(item.tool_name == requirement["tool"] and item.error is not None
                                 and item.error.code == requirement["code"] for item in observations.values())]
    evidence = getattr(decision, "evidence_refs", [])
    citation_errors = []
    valid_evidence = []
    for ref in evidence:
        source = observations.get(ref.observation_id)
        if (
            source is None
            or source.error is not None
            or any(
                getattr(ref, key, None) != getattr(source, key, None)
                for key in ("source_ref", "source_version", "content_hash")
            )
        ):
            citation_errors.append("unsupported_evidence:" + ref.observation_id)
        else:
            valid_evidence.append(source)
    cited_tools = {source.tool_name for source in valid_evidence}
    policy = getattr(decision, "policy_refs", [])
    hits = [
        hit
        for source in observations.values()
        if source.tool_name == "search_policy" and source.error is None
        for hit in (getattr(source, "result", None) or {}).get("hits", [])
    ]
    cited_rules = set()
    for ref in policy:
        if any(
            all(
                getattr(ref, key, None) == hit.get(key)
                for key in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")
            )
            for hit in hits
        ):
            cited_rules.add(ref.rule_id)
        else:
            citation_errors.append("unsupported_policy:" + ref.rule_id)
    missing_tools = sorted(set(gold["must_tools"]) - read_tools)
    missing_cited = sorted(set(gold["must_tools"]) - cited_tools) if action == "REFUND" else []
    missing_rules = sorted(set(gold["must_rules"]) - cited_rules)
    supported = valid_evidence if action == "REFUND" else list(observations.values())
    missing_support = [
        criterion["id"]
        for criterion in gold.get("support_requirements", [])
        if not any(_supports(source, option, case) for option in criterion["any_of"] for source in supported)
    ]
    action_ok = result.completed and action in gold["allowed_actions"]
    return {
        "action": action,
        "action_correct": action_ok,
        "forbidden_action": action in gold["forbidden_actions"],
        "missing_tools": missing_tools,
        "missing_cited_tools": missing_cited,
        "missing_rules": missing_rules,
        "citation_errors": citation_errors,
        "missing_support": missing_support,
        "missing_read_errors": missing_errors,
        "joint_correct": action_ok
        and not (missing_tools or missing_cited or missing_rules or citation_errors
                 or missing_support or missing_errors),
    }


def _supports(source, option, case):
    if source.error is not None or source.tool_name != option["tool"]:
        return False
    fields = source.result or {}
    if not all(fields.get(key) == value for key, value in option.get("fields", {}).items()):
        return False
    if "verification" not in option:
        return True
    if (
        case is None
        or fields.get("case_id") != case["case_id"]
        or fields.get("input_revision") != case["input_revision"]
    ):
        return False
    materials = case["review_context"]["materials"]
    refs = fields.get("evidence", [])
    # Snapshot is the input; the tool observation must anchor its exact registered source.
    checks = [m for m in materials if m["source_type"] == "REVIEWER_VERIFICATION"]
    latest = {
        m.get("reviewed_evidence_id"): m for m in sorted(checks, key=lambda m: (m["input_revision"], m["evidence_id"]))
    }
    targets = {m["evidence_id"] for m in materials if m["source_type"] == "CUSTOMER_STATEMENT"}
    return any(
        m.get("reviewed_evidence_id") in targets
        and m.get("verification_result") == option["verification"]
        and any(
            ref.get("observation_id") == m["evidence_id"]
            and all(ref.get(k) == m[k] for k in ("source_ref", "source_version", "content_hash"))
            for ref in refs
        )
        for m in latest.values()
    )


def score_rag(hits, query, gold, pin):
    ranked = [hit.rule_id for hit in hits]
    required = set(gold["must_rules"])
    violations = sum(
        hit.bundle_id != query["bundle_id"]
        or hit.merchant_id != query["merchant_id"]
        or hit.manifest_hash != pin["manifest_hash"]
        for hit in hits
    )
    return {
        "ranked_rules": ranked,
        "positive": bool(required),
        "violations": violations,
        **{
            f"coverage_at_{k}": len(required & set(ranked[:k])) / len(required) if required else None for k in (1, 2, 5)
        },
        "all_required_at_5": required <= set(ranked[:5]) if required else None,
        "negative_returned_candidates": bool(hits) if not required else None,
    }
