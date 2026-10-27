import datetime as dt
import json
from pathlib import Path

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SYSTEM, SupportAgent
from resolveflow.support.protocol import SupportInput
from tests.unit.test_support_agent import Reads, answer, read, request


def test_saved_signed_dispute_sees_repeated_read_progress_without_losing_raw_sources():
    raw = json.loads((Path(__file__).resolve().parents[3]
                      / 'agent/tests/fixtures/regressions/customer-agent-experience-v1/runtime-results.json').read_text(encoding='utf-8'))
    saved = next(r for r in raw['rows'] if r['id'] == 'U05' and r['turn'] == 1)
    original = {**saved['input'], 'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)}

    class SavedReads(Reads):
        def read(self, name, arguments):
            self.calls.append((name, arguments))
            return next(t['result'] for t in saved['tools'] if t['name'] == name)

    source = SavedReads()
    model = MockModelClient(script=[m['decision'] for m in saved['models'][:4]] + [
        answer(text='物流有签收记录，但您反馈未找到，仍需进一步核查。', citations=['O2']),
    ])
    result = SupportAgent(SupportInput.model_validate(original), model, source).run()
    assert result['status'] == 'SUCCEEDED'
    assert 'read_progress' not in model.packets[0]
    assert [p['read_progress']['outcome'] for p in model.packets[1:]] == [
        'NEW_EVIDENCE', 'NEW_EVIDENCE', 'UNCHANGED', 'UNCHANGED',
    ]
    assert model.packets[4]['read_progress'] == {
        'tool_name': 'get_shipment_trace', 'source_refs': ['O2'], 'outcome': 'UNCHANGED',
        'consecutive_unchanged': 2,
    }
    assert len(model.packets[4]['observations']) == 2
    assert model.packets[4]['observations'][1]['data'] == saved['tools'][1]['result']['data']
    assert len(source.calls) == 4


def test_changed_evidence_resets_progress_and_errors_or_empty_are_not_verified():
    class Changing(Reads):
        def read(self, name, arguments):
            self.calls.append((name, arguments))
            if len(self.calls) == 3:
                return {'error': 'SOURCE_UNAVAILABLE', 'retryable': True}
            return {'source_type': 'SHIPMENT', 'version': len(self.calls), 'data': {'status': 'IN_TRANSIT'}}

        def search(self, query, top_k):
            return []

    agent = SupportAgent(request(), MockModelClient(script=[]), Changing())
    agent.execute('get_shipment_trace', {})
    agent.execute('get_shipment_trace', {})
    assert agent._packet()['read_progress']['outcome'] == 'NEW_EVIDENCE'
    assert agent._packet()['read_progress']['consecutive_unchanged'] == 0
    agent.execute('get_shipment_trace', {})
    assert agent._packet()['read_progress']['outcome'] == 'ERROR'
    assert agent._packet()['read_progress']['source_refs'] == []
    agent.execute('search_policy', {'query': '资格', 'top_k': 1})
    assert agent._packet()['read_progress']['outcome'] == 'EMPTY'
    other = SupportAgent(request(), MockModelClient(script=[]), Reads())
    assert 'read_progress' not in other._packet()


def test_same_read_still_stops_at_original_no_progress_limit():
    model = MockModelClient(script=[read(), read(), read(), read()])
    source = Reads()
    result = SupportAgent(request(), model, source).run()
    assert result['reason'] == 'NO_PROGRESS' and len(source.calls) == 3
    assert model.packets[-1]['read_progress']['consecutive_unchanged'] == 2


def test_completion_instruction_distinguishes_customer_material_from_available_tool_work():
    assert '先查完能查事项' in SYSTEM and '勿以稍后核实结束' in SYSTEM
    assert 'NEEDS_CUSTOMER仅缺客户材料' in SYSTEM
    assert 'UNCHANGED' in SYSTEM
