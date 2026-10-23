"""Inspect actual SDK/provider packets: protected facts, exact tails and bounded local readback."""

from copy import deepcopy

from resolveflow.harness.context import canonical_json
from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request


def message(sequence, text, author="CUSTOMER"):
    return {"message_id": f"msg-{sequence}", "sequence": sequence, "author": author,
            "recipient": "ASSISTANT", "text": text}


def long_request():
    req = request(input_version=41)
    req.context["history"] = [message(n, "旧记录说明。" * 90 + f"尾部纠正{n}：家人并未代收。") for n in range(21, 41)]
    req.context["history"].append(message(41, req.context["current_request"]))
    req.context["history_before"] = 21
    return req


def test_history_is_compacted_to_real_request_budget_and_current_input_remains_exact():
    req = long_request()
    original = deepcopy(req.context)
    model = MockModelClient(script=[answer(citations=[])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    packet = model.packets[0]
    assert packet["current_request"] == req.context["current_request"]
    assert packet["context_layout"]["version"] == "support-layered-v2"
    assert (any(row["truncated"] and row["read_ref"] == "H21" for row in packet["history_index"])
            or "H21" in packet["history_read_refs"])
    assert all(m["sequence"] != 41 for m in packet["recent_messages"])
    assert len(canonical_json(packet).encode()) < len(canonical_json(req.context).encode())
    assert req.context == original


def test_model_can_read_tail_correction_without_network_or_losing_original_identity():
    req = long_request()
    raw = req.context["history"][0]["text"]
    source = Reads()
    model = MockModelClient(script=[
        read("read_context", reference="H21", offset=len(raw) - 16, limit=16),
        answer(text="已保留你对代收情况的纠正。", citations=["O1"]),
    ])
    result = SupportAgent(req, model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert source.calls == [] and result["spend"]["local_reads"] == 1
    quote = result["answer"]["citations"][0]
    assert quote["data"]["text"] == raw[-16:] and quote["data"]["message_id"] == "msg-21"
    assert quote["data"]["total_chars"] == len(raw) and quote["data"]["complete"] is False
    assert "尾部纠正21" in model.packets[1]["observations"][0]["data"]["text"]


def test_identical_reads_are_deduplicated_but_conflicting_versions_and_conditions_are_kept():
    class Versions(Reads):
        def read(self, name, arguments):
            self.calls.append((name, arguments))
            version = 1 if len(self.calls) < 3 else 2
            return {"source_type": "ORDER", "version": version, "data": {"paid_amount_minor": 32900,
                    "status": "NOT_SHIPPED" if version == 1 else "DELIVERED"}}

    model = MockModelClient(script=[read(), read(), read(),
                                   {"kind": "SEARCH_POLICY", "query": "订单状态与条件", "top_k": 3}, answer()])
    result = SupportAgent(request(), model, Versions()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    observed = model.packets[-1]["observations"]
    assert len(observed) == 3
    assert [o["version"] for o in observed if o["source_type"] == "ORDER"] == [1, 2]
    assert all(o["data"]["paid_amount_minor"] == 32900 for o in observed if o["source_type"] == "ORDER")
    assert observed[-1]["data"]["text"] == "有签收争议时须商家核验，不因客户陈述直接退款。"


def test_required_overflow_does_not_call_model_or_silently_drop_current_request():
    req = request()
    req.context["current_request"] = "必须保留。" * 4000
    model = MockModelClient(script=[answer(citations=[])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["reason"] == "CONTEXT_REQUIRED_OVERFLOW" and model.calls == 0


def test_unknown_readback_reference_is_an_observation_not_arbitrary_history_access():
    source = Reads()
    model = MockModelClient(script=[read("read_context", reference="H999", offset=0, limit=20),
                                   answer(citations=[])])
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.packets[-1]["observations"][0]["error"] == "CONTEXT_REFERENCE_NOT_FOUND"
    assert source.calls == []


def test_large_remote_history_is_indexed_then_exact_tail_is_locally_readable():
    raw = "不是物流政策。" * 500 + "补充纠正：我没有收到。"

    class History(Reads):
        def read(self, name, arguments):
            assert name == "read_history"
            self.calls.append((name, arguments))
            return {"source_type": "CONVERSATION", "version": 2,
                    "data": {"version": 2, "messages": [message(1, raw)]}}

    source = History()
    model = MockModelClient(script=[read("read_history", limit=1),
                                   read("read_context", reference="H1", offset=len(raw) - 12, limit=12),
                                   answer(text="你反馈未收到。", citations=["O2"])])
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert len(source.calls) == 1 and result["spend"]["local_reads"] == 2
    assert result["answer"]["citations"][0]["data"]["text"] == raw[-12:]
    assert len(canonical_json(model.packets[1]).encode()) < len(raw.encode())


def test_recent_customer_correction_is_exact_not_only_the_old_first_160_characters():
    req = request(input_version=5)
    raw = "说明情况。" * 60 + "纠正：之前说代收是我记错了，实际没有。"
    req.context["history"] = [message(3, raw)]
    model = MockModelClient(script=[answer(citations=[])])
    assert SupportAgent(req, model, Reads()).run()["status"] == "SUCCEEDED"
    assert model.packets[0]["recent_messages"][0]["text"] == raw


def test_protected_policy_conditions_are_not_deleted_to_fit_a_small_context():
    class Policies(Reads):
        def search(self, query, top_k):
            return [{"source_type": "POLICY", "version": n, "data": {
                "text": "退款条件与例外必须保留。" * 150, "rule_id": str(n)}} for n in range(3)]

    model = MockModelClient(script=[{"kind": "SEARCH_POLICY", "query": "条件", "top_k": 3}, answer(citations=[])])
    agent = SupportAgent(request(), model, Policies())
    result = agent.run()
    assert result["reason"] == "CONTEXT_REQUIRED_OVERFLOW" and model.calls == 1
    assert len(agent.citations) == 3 and all("例外" in o["data"]["text"] for o in agent.observations)


def test_history_authority_is_explicit_without_rewriting_text_or_promoting_it_to_facts():
    from resolveflow.support.context import render_context

    req = request(input_version=4)
    req.context['history'] = [message(1, '之前查到运输延迟。', 'ASSISTANT'), message(2, '假如之后丢失呢？')]
    before = deepcopy(req.context)
    packet = render_context(req, {}, [])
    assert packet['recent_messages'][0]['authority'] == 'HISTORICAL_ASSISTANT_OUTPUT'
    assert packet['recent_messages'][1]['authority'] == 'CUSTOMER_STATEMENT'
    assert packet['recent_messages'][0]['text'] == '之前查到运输延迟。'
    assert packet['fact_view'] == [] and req.context == before
    indexed = render_context(req, {}, [], recent=0)
    assert indexed['history_index'][0]['authority'] == 'HISTORICAL_ASSISTANT_OUTPUT'
