"""Dry-run the exact one-turn driver with synthetic Provider SSE; never calls a real LLM."""

import hashlib
import json

import httpx
from scripts import confirm_policy_focus_live_v1 as driver


def test_exact_driver_exports_and_cleans_its_schema_without_touching_the_public_ledger(
    postgres_dsn, tmp_path, monkeypatch,
):
    original_model = driver.RecordedStreamingModel
    fixture = driver.build_fixture()
    text = fixture['original_input']['context']['current_request']
    script = [
        {'kind': 'TURN_UNDERSTANDING', 'focus': [
            {'id': 't2', 'intent': 'OTHER', 'request': '讨论运输中与未来假设的政策条件', 'needs': ['POLICY']}],
         'dialogue_events': [{'change': 'ADD', 'task_ids': ['t2'], 'reference': 'CURRENT', 'quote': text}]},
        {'kind': 'READ_TOOL', 'tool_name': 'search_policy', 'arguments': {'query': '当前与假设条件',
            'sub_queries': ['运输延迟 包裹在途 退款条件', '假如承运商以后确认丢失 人工核验 退款条件'], 'top_k': 3}},
        {'kind': 'ANSWER_PARTS', 'parts': [{'task_id': 't2', 'status': 'ANSWERED',
            'text': '仅解释政策，尚不认定当前资格；条件变化后仍须核验。', 'citations': ['P1', 'P2']}]},
    ]
    sent = []

    def provider(request):
        decision = script[len(sent)]
        sent.append(request)
        content = json.dumps(decision, ensure_ascii=False)
        frames = [{'choices': [{'delta': {'content': content}}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}],
                   'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}]
        data = ''.join('data: ' + json.dumps(f, ensure_ascii=False) + '\n\n' for f in frames) + 'data: [DONE]\n\n'
        return httpx.Response(200, content=data.encode())

    class SyntheticProvider(original_model):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, stream_transport=httpx.MockTransport(provider))

    output = tmp_path / 'report'
    output.mkdir()
    path = driver.ROOT / 'scripts/confirm_policy_focus_live_v1.py'
    driver.persist(output / 'input.json', fixture)
    driver.persist(output / 'manifest.json', {'model_attempt_limit': 12,
        'files': {'scripts/confirm_policy_focus_live_v1.py': hashlib.sha256(path.read_bytes()).hexdigest()}})
    ledger = tmp_path / 'usage.json'
    driver.persist(ledger, {'used': 0})
    monkeypatch.setattr(driver, 'OUT', output)
    monkeypatch.setattr(driver, 'LEDGER', ledger)
    monkeypatch.setattr(driver, 'DSN', postgres_dsn)
    monkeypatch.setattr(driver, 'RecordedStreamingModel', SyntheticProvider)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'synthetic-key')
    driver.execute()
    result = driver.read(output / 'runtime-results.json')
    assert result['state'] == 'FINISHED' and result['result']['status'] == 'SUCCEEDED'
    assert result['transport_requests'] == 3 and result['ledger_after'] == 3
    assert result['public_data_unchanged'] and result['temporary_schema_removed']
    assert len(sent) == 3 and not ledger.with_name(ledger.name + '.lock').exists()
