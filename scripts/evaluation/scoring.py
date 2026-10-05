"""Independent scores: valid action plus factual/policy support, never transcript order."""

from __future__ import annotations


def score_agent(result, gold):
    decision = result.decision
    action = getattr(decision, "recommended_action", None)
    if getattr(decision, "kind", None) == "ASK_CUSTOMER":
        action = "REQUEST_INFO"
    elif getattr(decision, "kind", None) == "ESCALATE":
        action = "MANUAL_REVIEW"
    observations = {item.observation_id: item for item in result.observations}
    read_tools = {item.tool_name for item in observations.values() if item.error is None}
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
    action_ok = result.completed and action in gold["allowed_actions"]
    return {
        "action": action,
        "action_correct": action_ok,
        "forbidden_action": action in gold["forbidden_actions"],
        "missing_tools": missing_tools,
        "missing_cited_tools": missing_cited,
        "missing_rules": missing_rules,
        "citation_errors": citation_errors,
        "joint_correct": action_ok and not (missing_tools or missing_cited or missing_rules or citation_errors),
    }


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
