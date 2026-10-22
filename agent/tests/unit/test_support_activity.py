from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request


def test_packet_keeps_order_and_repeated_attempts_separate_from_deduplicated_evidence():
    model = MockModelClient(script=[read('get_order_context'), read(), read(), answer(citations=['O1'])])
    agent = SupportAgent(request(), model, Reads())
    assert agent.run()['status'] == 'SUCCEEDED'
    assert 'recent_actions' not in model.packets[0] and 'recent_actions' not in model.packets[1]
    actions = model.packets[3]['recent_actions']
    assert [a['tool_name'] for a in actions] == ['get_order_context', 'get_shipment_trace']
    assert [a['attempts'] for a in actions] == [1, 2]
    assert actions[1]['arguments'] == {} and actions[1]['outcome'] == 'UNCHANGED'
    assert actions[1]['source_refs'] == ['O1']
    assert len(model.packets[3]['observations']) == 1


def test_bounded_activity_retains_last_three_distinct_queries_and_counts_omitted_groups():
    agent = SupportAgent(request(), MockModelClient(script=[]), Reads())
    for i in range(5):
        agent.execute('search_policy', {'query': str(i), 'top_k': 1})
    packet = agent._packet()
    assert [a['arguments']['query'] for a in packet['recent_actions']] == ['2', '3', '4']
    assert packet['omitted_action_groups'] == 2
    assert agent._packet()['recent_actions'] == packet['recent_actions']
    packet['recent_actions'][0]['arguments']['query'] = 'mutated'
    assert agent._packet()['recent_actions'][0]['arguments']['query'] == '2'


def test_errors_and_later_success_are_different_actions_and_feedback_is_not_an_action():
    class Recovers(Reads):
        def read(self, name, arguments):
            if not self.calls:
                self.calls.append((name, arguments))
                return {'error': 'SOURCE_UNAVAILABLE', 'retryable': True}
            return super().read(name, arguments)

    agent = SupportAgent(request(), MockModelClient(script=[]), Recovers())
    agent.execute('get_shipment_trace', {})
    agent.execute('get_shipment_trace', {})
    before = agent._packet()['recent_actions']
    assert [a['outcome'] for a in before] == ['ERROR', 'NEW_EVIDENCE']
    assert before[0]['errors'] == ['SOURCE_UNAVAILABLE']
    agent.feedback = 'format error'
    agent.execute('__support_feedback', {})
    assert agent._packet()['recent_actions'] == before
    assert 'recent_actions' not in SupportAgent(request(), MockModelClient(script=[]), Reads())._packet()
