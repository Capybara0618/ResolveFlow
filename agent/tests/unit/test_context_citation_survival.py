"""Real-provider badcase: trimming must never turn known sources into guessed policy citations."""

from resolveflow.harness.context import ContextBuilder
from resolveflow.harness.facts import FactsView
from resolveflow.harness.observation_read import ObservationStore
from tests.unit.test_context_builder import observation
from resolveflow.harness.context import canonical_json, estimate_tokens


def test_policy_identity_and_complete_condition_survive_an_oversized_optional_result():
    hit = {"bundle_id": "pinned-bundle", "version": "v7", "rule_id": "R-EXCEPTION", "chunk_id": "c-4",
           "content_hash": "b" * 64, "text": "可以退款，但单笔超过5000元必须人工复核。"}
    source = observation(tool="search_policy", source_ref="policy:pinned-bundle",
                         result={"hits": [hit], "irrelevant_debug": "x" * 9000})
    packet = ContextBuilder(system_prompt="Choose one JSON action.").build(
        run_id="r", case_id="c", input_revision=1, line_id="l", step=2, manifest_id="m",
        description="请审查退款", observations=[source], view=FactsView(), tool_schema={}, cumulative_remaining=850)
    text = "\n".join(message["content"] for message in packet.messages)
    for item in ("R-EXCEPTION", "c-4", "v7", "b" * 64, "但单笔超过5000元必须人工复核"):
        assert item in text


def test_readback_carries_original_citation_in_addition_to_window_identity():
    source = observation(source_ref="order:one", content_hash="c" * 64, observation_id="obs-original")
    store = ObservationStore("run-one")
    store.remember(source)
    window = store.read("obs-original", limit=100)
    assert window.as_result()["citation"] == {
        "observation_id": "obs-original", "source_ref": "order:one", "source_version": "3",
        "content_hash": "c" * 64,
    }


def test_packet_reservation_also_covers_json_escaping_in_the_actual_deepseek_body():
    from resolveflow.harness.sdk_adapter import raw_text_message
    from resolveflow.runtime.factory import DeploymentConfig, _live_client
    source = observation(result={"text": '原文中的"报价"与\\路径' * 50})
    packet = ContextBuilder(system_prompt="Return JSON", provider_capacity=32768).build(
        run_id="r", case_id="c", input_revision=1, line_id="l", step=2, manifest_id="m",
        description="请审查退款", observations=[source], view=FactsView(), tool_schema={})
    client = _live_client(DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"))
    body = client.prepare_request(system="", messages=[
        raw_text_message(item["content"], role=item["role"]) for item in packet.messages
    ], max_output_tokens=1024)
    assert estimate_tokens(canonical_json(body)) <= packet.input_tokens <= 8192
