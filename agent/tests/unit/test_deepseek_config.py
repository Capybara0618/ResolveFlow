"""Provider configuration is part of the recorded request and cannot widen the harness ceiling."""

from resolveflow.runtime.factory import DeploymentConfig, _live_client
from resolveflow.harness.vocabulary import HARNESS_SYSTEM_PROMPT
from resolveflow.harness.manifest import model_block_for


def test_deepseek_json_nonthinking_parameters_are_recorded_and_output_is_capped():
    client = _live_client(DeploymentConfig(mode="live", provider="deepseek",
                          endpoint="https://api.deepseek.com/chat/completions", model_id="deepseek-flash"))
    body = client.prepare_request(system=HARNESS_SYSTEM_PROMPT, messages=[], max_output_tokens=1024)
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 1024
    assert "json" in body["messages"][0]["content"].lower()
    assert "Authorization" not in body
    assert model_block_for(client, context_window_tokens=8192)["parameters"]["thinking"] == {"type": "disabled"}
    assert model_block_for(client, context_window_tokens=8192)["parameters"]["response_format"] == {"type": "json_object"}


def test_other_provider_does_not_receive_deepseek_specific_parameters():
    client = _live_client(DeploymentConfig(mode="live", provider="other", endpoint="https://example.invalid",
                          model_id="other"))
    body = client.prepare_request(system="Return JSON.", messages=[], max_output_tokens=100)
    assert "thinking" not in body


def test_deployment_capacity_is_explicit_and_does_not_raise_the_step_ceiling():
    from resolveflow.harness.context import ContextBuilder
    config = DeploymentConfig.from_environ({"RESOLVEFLOW_MODEL_MODE": "live",
        "RESOLVEFLOW_MODEL_CONTEXT_WINDOW_TOKENS": "32768"})
    assert config.context_window_tokens == 32768
    assert ContextBuilder(system_prompt="JSON", provider_capacity=config.context_window_tokens).input_cap() == 8192
