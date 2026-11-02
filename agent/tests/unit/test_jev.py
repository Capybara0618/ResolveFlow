import json

import httpx
import pytest

from resolveflow.support.jev import JevClient, JevConfig, JevError, build_request, load_local_env


def response(**updates):
    return {
        "model": "jev-1.14.0",
        "answers": {"grounding": {"type": "choice", "choice": "contradicted", "confidence": 0.98,
                                 "probabilities": {"supported": 0.0, "contradicted": 0.99,
                                                   "insufficient_evidence": 0.01}}},
        "usage": {"input_tokens": 420, "output_tokens": 50},
        **updates,
    }


def test_configuration_is_explicit_pinned_and_secret_is_not_printable():
    assert not JevConfig.from_environ({}).enabled
    config = JevConfig.from_environ({"RESOLVEFLOW_JEV_ENABLED": "1", "TYPESAFE_API_KEY": "test-secret"})
    assert config.enabled and config.model == "jev-1.14.0"
    assert "test-secret" not in repr(config) and "test-secret" not in json.dumps(config.manifest())
    for env in ({"RESOLVEFLOW_JEV_ENABLED": "yes"}, {"RESOLVEFLOW_JEV_ENABLED": "1"},
                {"RESOLVEFLOW_JEV_MODEL": "jev-latest"}, {"RESOLVEFLOW_JEV_TIMEOUT_SECONDS": "nan"},
                {"RESOLVEFLOW_JEV_ENDPOINT": "https://another-host.invalid"}):
        with pytest.raises(ValueError):
            JevConfig.from_environ(env)


def test_env_file_only_loads_jev_names_and_explicit_environment_wins(tmp_path):
    path = tmp_path / ".env"
    path.write_text('TYPESAFE_API_KEY="local-test"\nRESOLVEFLOW_JEV_ENABLED=1\n'
                    'RESOLVEFLOW_MODEL_ID=do-not-change\nUNRELATED=ignored\n', encoding="utf-8")
    env = {"TYPESAFE_API_KEY": "explicit-test"}
    load_local_env(path, env)
    assert env == {"TYPESAFE_API_KEY": "explicit-test", "RESOLVEFLOW_JEV_ENABLED": "1"}


def test_request_keeps_failed_and_conflicting_reads_without_inventing_facts():
    observations = [{"source_id": "O1", "version": 2, "data": {"status": "LOST"}},
                    {"error": "SOURCE_UNAVAILABLE", "retryable": True}]
    body = build_request(JevConfig(), "包裹丢了吗？", {"text": "包裹已丢失。", "citations": []}, observations)
    assert body["state"]["observations"] == observations
    assert body["state"]["answer"] == "包裹已丢失。"
    assert set(body["questions"]["grounding"]["criteria"]) == {
        "supported", "contradicted", "insufficient_evidence"}


def test_official_request_and_typed_response_with_actual_usage():
    calls = []

    def send(req):
        calls.append(req)
        return httpx.Response(200, json=response())

    result = JevClient(JevConfig(api_key="test-secret"), transport=httpx.MockTransport(send)).evaluate({"state": {}})
    assert len(calls) == 1
    assert str(calls[0].url) == "https://api.typesafe.ai/v1/systemone"
    assert calls[0].headers["Authorization"] == "Bearer test-secret"
    assert result["verdict"] == "contradicted" and result["usage"]["input_tokens"] == 420
    assert result["response"]["model"] == "jev-1.14.0"


@pytest.mark.parametrize("status", [302, 401, 402, 429, 500])
def test_http_failure_has_no_retry_or_secret_leak(status):
    calls = []

    def send(req):
        calls.append(req)
        return httpx.Response(status, text="test-secret should not be saved",
                              headers={"Location": "https://another-host.invalid"})

    with pytest.raises(JevError) as error:
        JevClient(JevConfig(api_key="test-secret"), transport=httpx.MockTransport(send)).evaluate({})
    assert len(calls) == 1 and error.value.reason == f"HTTP_{status}"
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("body", [{}, {"model": "unexpected"}, response(answers={}),
                                response(usage={"input_tokens": True, "output_tokens": 5}),
                                response(model="jev-latest")])
def test_invalid_response_cannot_become_a_pass(body):
    with pytest.raises(JevError, match="INVALID_RESPONSE"):
        JevClient(JevConfig(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))).evaluate({})


def test_timeout_is_not_a_semantic_verdict():
    def send(req):
        raise httpx.ReadTimeout("test-secret", request=req)

    with pytest.raises(JevError, match="TIMEOUT"):
        JevClient(JevConfig(), transport=httpx.MockTransport(send)).evaluate({})
