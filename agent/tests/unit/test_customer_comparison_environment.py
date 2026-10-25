"""Neutral external clients expose raw sources and count provider transmissions, not Agent logic."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from scripts.evaluation.customer_comparison_environment import (
    PlainChatClient,
    RawPolicyService,
    RequestAllowance,
    guide_data,
    text_prefix,
    transport_for,
)


def stream_response(text, *, usage=True):
    items = [{"model": "deepseek-flash", "choices": [{"delta": {"content": c}}]} for c in text]
    items.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    if usage:
        items.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}})
    return "\n\n".join('data: ' + json.dumps(x, ensure_ascii=False) for x in items) + '\n\ndata: [DONE]\n\n'


def test_plain_client_counts_once_and_keeps_real_usage_and_retained_text_time():
    ledger = {"used": 10, "save": lambda: None}
    budget = RequestAllowance(ledger, 10, 1)
    bodies = []
    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, text=stream_response('{"text":"你好","refund_summary":null}'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        model = PlainChatClient(http, "https://provider.test/chat", "secret", budget)
        result = model.complete(stage="ANSWER", messages=[{"role": "user", "content": "问题"}], max_output_tokens=1024)
        assert result.usage == {"input_tokens": 12, "output_tokens": 8, "estimated": False}
        assert result.first_text_ms is not None and result.mode == "live" and model.last_sent
        assert ledger["used"] == 11 and bodies[0]["thinking"] == {"type": "disabled"}
        with pytest.raises(RuntimeError, match="BUDGET_EXHAUSTED"):
            model.complete(stage="ROUTE", messages=[], max_output_tokens=1024)
        assert ledger["used"] == 11 and not model.last_sent
        assert "secret" not in json.dumps(model.last_request)


def test_transport_failure_still_consumes_one_attempt_and_unknown_usage_is_not_estimated():
    ledger = {"used": 0, "save": lambda: None}
    def broken(req):
        raise httpx.ConnectTimeout("timeout", request=req)
    with httpx.Client(transport=httpx.MockTransport(broken)) as http:
        model = PlainChatClient(http, "https://provider.test/chat", "secret", RequestAllowance(ledger, 0, 2))
        with pytest.raises(httpx.ConnectTimeout):
            model.complete(stage="ANSWER", messages=[], max_output_tokens=100)
        assert ledger["used"] == 1 and model.last_sent
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            text=stream_response('{"text":"解释"}', usage=False)))) as http:
        model = PlainChatClient(http, "https://provider.test/chat", "secret", RequestAllowance(ledger, 0, 2))
        assert model.complete(stage="ANSWER", messages=[], max_output_tokens=100).usage is None


def test_frozen_source_transport_binds_run_and_preserves_errors_and_history():
    identity = {"run_id": "r", "conversation_id": "c", "input_version": 3}
    snapshot = {"http_status": {"get_order_context": 404, "get_shipment_trace": 503},
        "facts": {"get_order_context": {"error": "NOT_FOUND"}, "get_shipment_trace": {"error": "DOWN"}}}
    paths = []
    with httpx.Client(transport=httpx.MockTransport(transport_for(snapshot, identity,
            [{"sequence": 1, "text": "旧原文"}, {"sequence": 3, "text": "当前"}], paths))) as http:
        prefix = "http://frozen.test/internal/v1/support/turns/r"
        assert http.get(prefix + "/facts/order").status_code == 404
        assert http.get(prefix + "/facts/shipment").json() == {"error": "DOWN"}
        assert http.get(prefix + "/facts/history?before_sequence=3&limit=5").json()["messages"] == [
            {"sequence": 1, "text": "旧原文"}]
        assert http.get(prefix.replace('/r', '/foreign') + "/facts/order").status_code == 403
        assert http.post(prefix + "/refund").status_code == 403
    assert len(paths) == 5


def test_raw_policy_service_keeps_bound_generation_and_rejects_other_subject_or_large_sets():
    class Index:
        def require_ready(self, bundles, manifest):
            return [SimpleNamespace(bundle_id='b', generation_id='g', merchant_id='M')]
        def small_context(self, **_):
            return [SimpleNamespace(bundle_id='b', merchant_id='M', manifest_hash='h', rule_id='r', chunk_id='c',
                content_hash='s', text='原政策全文', version='v', title='政策')]
    service = RawPolicyService(Index())
    manifest = {"merchant_id": "M", "bundle_ids": ["b"], "manifest_hash": "h"}
    value = service.search("M", manifest, {"b": "g"}, "查询")
    assert value[0]["data"]["text"] == '原政策全文' and value[0]["retrieval_context"]["mode"] == 'COMPLETE_SMALL_SET'
    with pytest.raises(ValueError, match="scope"):
        service.search("foreign", manifest, {"b": "g"}, "查询")
    with pytest.raises(ValueError, match="generation"):
        service.search("M", manifest, {"b": "new"}, "查询")
    index = Index()
    index.small_context = lambda **_: None
    with pytest.raises(ValueError, match="small policy"):
        RawPolicyService(index).search("M", manifest, {"b": "g"}, "查询")


def test_public_guide_raw_data_is_identical_without_importing_agent_guide_builder():
    from resolveflow.support.guide import guide_source
    assert guide_data() == guide_source()


@pytest.mark.parametrize(("raw", "expected"), [('{', None), ('{"text":"', None),
    ('{"route":"你好"', None), ('{"nested":{"text":"不是正文"}', None),
    ('{"text":"\\u4f', None), ('{"text":"\\u4f60', '你'),
    ('{"text":"你\\', '你'), ('{"citations":[],"text":"你好', '你好')])
def test_partial_json_timer_reads_only_body(raw, expected):
    assert text_prefix(raw) == expected


def test_truncated_or_length_limited_stream_cannot_publish_partial_body():
    for raw in (stream_response('{"text":"解释"}').replace('data: [DONE]', ''),
            stream_response('{"text":"解释"}').replace('"stop"', '"length"')):
        with httpx.Client(transport=httpx.MockTransport(lambda _, raw=raw: httpx.Response(200, text=raw))) as http:
            ledger = {"used": 0, "save": lambda: None}
            model = PlainChatClient(http, "https://provider.test/chat", "secret", RequestAllowance(ledger, 0, 1))
            with pytest.raises(ValueError, match="finished response"):
                model.complete(stage="ANSWER", messages=[], max_output_tokens=100)
            assert ledger["used"] == 1


def test_neutral_environment_does_not_import_production_agent():
    from scripts.evaluation import customer_comparison_environment as module
    tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
    names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(n.startswith('resolveflow') for n in names)


def test_shared_tokenizer_counts_like_agent_but_does_not_apply_agent_context_logic():
    from scripts.evaluation.customer_comparison_environment import wire_tokens

    from resolveflow.harness.token_counting import FLASH_VERSION, InputCounter
    body = {'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': '核查物流 signed；金额123.00'}],
        'max_tokens': 1024}
    assert wire_tokens(body) == InputCounter(FLASH_VERSION).count(body)


def test_input_window_overflow_does_not_consume_provider_allowance():
    ledger = {'used': 0, 'save': lambda: None}
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('must not send'))) as http:
        model = PlainChatClient(http, 'https://provider.test/chat', 'test', RequestAllowance(ledger, 0, 1))
        with pytest.raises(ValueError, match='INPUT_WINDOW_EXCEEDED'):
            model.complete(stage='ANSWER', messages=[{'role': 'user', 'content': '测试文本' * 10000}],
                max_output_tokens=1024)
    assert ledger['used'] == 0 and not model.last_sent
