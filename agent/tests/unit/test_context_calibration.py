"""Provider counting and lossless policy compaction must not loosen source guards."""

from types import SimpleNamespace

import pytest
from resolveflow.harness.context import ContextBuilder, canonical_json, estimate_tokens
from resolveflow.harness.facts import FactsView
from resolveflow.harness.references import ReferenceCatalog, expand_references
from resolveflow.harness.token_counting import counter_for

from tests.unit.test_context_builder import observation


def test_flash_counter_is_model_bound_and_covers_json_and_message_content():
    body = {"messages": [{"role": "user", "content": '退款条件与"来源"\\版本' * 100}]}
    counter = counter_for(SimpleNamespace(provider="deepseek", model_id="deepseek-flash"))
    assert counter.mode == "ESTIMATED_DEEPSEEK_V41_JSON"  # noqa: S105
    assert 0 < counter.count(body) < estimate_tokens(canonical_json(body))
    assert "81f64d1248a68ce3" in counter.version
    for client in [SimpleNamespace(provider="other", model_id="deepseek-flash"),
                   SimpleNamespace(provider="deepseek", model_id="unknown")]:
        other = counter_for(client)
        assert other.count(body) == estimate_tokens(canonical_json(body))


def test_large_required_content_is_counted_and_never_silently_trimmed():
    counter = counter_for(SimpleNamespace(provider="deepseek", model_id="deepseek-flash"))
    builder = ContextBuilder(system_prompt="Return JSON", counter=counter)
    packet = builder.build(run_id="r", case_id="c", step=1, input_revision=1, line_id="l",
                           description="请按完整政策处理退款。" * 130, manifest_id="m",
                           view=FactsView(), observations=[], tool_schema={})
    assert packet.token_count_mode == counter.mode
    assert packet.input_tokens == counter.count({"messages": packet.messages}) + 256
    assert ("请按完整政策处理退款。" * 130) in packet.messages[-1]["content"]


def test_policy_table_retains_versions_exceptions_and_expands_only_exact_refs():
    hits = [{"bundle_id": "b" * 36, "version": "v1", "rule_id": f"R-{i}", "chunk_id": f"c-{i}",
             "content_hash": str(i) * 64, "text": f"规则{i}。必须人工核验；超过限额须人工处理。"}
            for i in range(1, 5)]
    source = observation(tool="search_policy", result={"hits": hits})
    packet = ContextBuilder(system_prompt="Rules").build(
        run_id="r", case_id="c", step=1, input_revision=1, line_id="l", description="退款",
        manifest_id="m", view=FactsView(), observations=[source], tool_schema={"reference_format": "run-short-v1"})
    text = packet.messages[-1]["content"]
    assert "policy_table" in text
    for hit in hits:
        assert hit["text"] in text
        alias = ReferenceCatalog([source]).policy(hit)["ref"]
        expanded = expand_references({"policy_refs": [alias]}, packet.references, packet.read_ids)
        assert expanded["policy_refs"] == [{k: hit[k] for k in
                                            ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}]
    assert text.count('"bundle_id"') == 1


def test_asset_corruption_is_not_a_silent_fallback(tmp_path):
    from resolveflow.harness.token_counting import load_tokenizer
    path = tmp_path / "bad.gz"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="tokenizer integrity"):
        load_tokenizer(path)


def test_unknown_reference_feedback_does_not_cite_failed_or_local_sources():
    from resolveflow.harness.actions import ActionRefusedError
    catalog = ReferenceCatalog([observation(observation_id="real")])
    catalog.evidence({"observation_id": "real", "source_ref": "order:line", "source_version": "3",
                      "content_hash": "a" * 64})
    # Use exactly the registered map; the registry never invents an alias from a failed read.
    with pytest.raises(ActionRefusedError, match="available evidence aliases") as caught:
        expand_references({"evidence_refs": ["O404"]}, catalog.references, catalog.read_ids)
    assert caught.value.reason_code == "ACTION_CITATION_INVALID"


def test_invalid_wrapper_feedback_preserves_one_repair_then_safe_stop():
    from resolveflow.harness.model import MockModelClient
    from resolveflow.harness.sdk_runner import AgentScopeRunner

    from tests.unit.test_harness_loop import FACTS, StubTools
    invalid = {"type": "json_object", "kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]}
    model = MockModelClient(script=[invalid, {"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]}])
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    assert result.completed and result.decision.kind == "ESCALATE"
    assert result.spend.model_calls == 2
    assert any('"kind":"ESCALATE"' in n and "no type/action wrapper" in n for n in result.notices)
    stopped = AgentScopeRunner(model=MockModelClient(script=[invalid, invalid]), tools=StubTools(), facts=FACTS).run()
    assert not stopped.completed and stopped.spend.model_calls == 2
