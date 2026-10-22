"""Critical order values are rendered from scoped evidence, never product display metadata."""

import pytest

from tests.unit.test_support_agent import Reads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


class FactReads(Reads):
    def read(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_order_context":
            return {"source_type": "ORDER", "version": 2, "data": {"order_line": {
                "line_id": "line-A", "status": "PAID", "line_paid_amount": 12345, "currency": "CNY"}}}
        return {"source_type": "SHIPMENT", "version": 3, "data": {"line_id": "line-A",
                "status": "LOST", "carrier_conclusion": "LOST"}}


def test_program_renders_current_paid_amount_and_status_from_distinct_authorities():
    req = request()
    req.context["product"]["amount_minor"] = 99900
    piece = part("trace", "订单{{ORDER_STATUS}}，承运结论{{CARRIER_CONCLUSION}}，实付{{PAID_AMOUNT}}。")
    piece["facts"] = [{"field": field, "source": source} for field, source in [
        ("ORDER_STATUS", "O2"), ("PAID_AMOUNT", "O2"), ("CARRIER_CONCLUSION", "O1")]]
    result, _, source, _ = staged(req, [understand(req, needs=["SHIPMENT"]), read(),
        read("get_order_context"), parts(piece)], FactReads())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["text"] == "订单PAID，承运结论LOST，实付123.45 CNY。"
    assert {c["source_id"] for c in result["answer"]["citations"]} == {"O1", "O2"}
    assert len(source.calls) == 2


@pytest.mark.parametrize("source,field", [("O1", "PAID_AMOUNT"), ("O8", "ORDER_STATUS"),
                                         ("O1", "ORDER_STATUS")])
def test_wrong_source_type_or_unread_source_cannot_supply_order_fact(source, field):
    req = request()
    piece = part("trace", "事实{{" + field + "}}", ["O1"])
    piece["facts"] = [{"field": field, "source": source}]
    result, model, _, _ = staged(req, [understand(req), read(), parts(piece), parts(piece)], FactReads())
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert model.calls == 4


@pytest.mark.parametrize("text", ["本单实付129.00 CNY。", "本单实付￥129。", "本单实付129元。"])
def test_numeric_money_requires_current_order_source_even_when_product_amount_is_available(text):
    req = request()
    req.context["product"]["amount_minor"] = 12900
    bad = parts(part("trace", text, ["O1"]))
    result, model, _, _ = staged(req, [understand(req), read(), bad, bad], FactReads())
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert "ORDER" in model.packets[-1]["feedback"]


def test_general_policy_can_describe_whole_paid_amount_without_reading_order():
    req = request()
    final = parts(part("trace", "规则按整行实付金额计算；具体金额尚未核实。"))
    result, _, source, _ = staged(req, [understand(req, needs=[]), final], FactReads())
    assert result["status"] == "SUCCEEDED" and source.calls == []


def test_fact_cannot_read_another_line_or_accept_model_supplied_value():
    from resolveflow.support.grounding import ground_answer
    from resolveflow.support.protocol import AnswerParts

    req = request()
    piece = part("trace", "实付{{PAID_AMOUNT}}")
    piece["facts"] = [{"field": "PAID_AMOUNT", "source": "O1"}]
    decision = AnswerParts.model_validate(parts(piece))
    source = FactReads().read("get_order_context", {})
    source["data"]["order_line"]["line_id"] = "foreign"
    with pytest.raises(ValueError):
        ground_answer(decision, req, {"O1": source})
    piece["facts"][0]["value"] = 12900
    with pytest.raises(ValueError):
        AnswerParts.model_validate(parts(piece))


def test_current_order_reference_does_not_make_a_wrong_literal_amount_valid():
    req = request()
    bad = parts(part("trace", "本单实付129元。", ["O1"]))
    result, _, _, _ = staged(req, [understand(req, needs=["ORDER"]), read("get_order_context"), bad, bad],
                              FactReads())
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"


@pytest.mark.parametrize("field", ["version", "currency", "line_paid_amount"])
def test_incomplete_order_source_is_not_completed_from_product_metadata(field):
    from resolveflow.support.grounding import value_for

    req = request()
    source = FactReads().read("get_order_context", {})
    if field == "version":
        del source[field]
    else:
        del source["data"]["order_line"][field]
    with pytest.raises(ValueError):
        value_for("PAID_AMOUNT", source, req)


def test_fact_feedback_also_exposes_missing_stage_sources_before_the_only_repair():
    import json

    from resolveflow.support.guide import guide_source

    class Sources(FactReads):
        def read(self, name, arguments):
            if name == 'get_support_guide':
                self.calls.append((name, arguments))
                return guide_source()
            return super().read(name, arguments)

    req = request()
    bad = part('trace', '承运记录已签收。', ['O1'])
    bad['facts'] = [{'field': 'SHIPMENT_STATUS', 'source': 'O1'}]
    fixed = part('trace', '承运记录{{SHIPMENT_STATUS}}；可请商家核查。', ['O1', 'O2'])
    fixed['facts'] = bad['facts']
    result, model, source, _ = staged(req, [understand(req, needs=['SHIPMENT', 'GUIDE']), read(),
        parts(bad), read('get_support_guide'), parts(fixed)], Sources())
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[3]['feedback'])
    assert feedback['field'] == 'answer_facts'
    assert feedback['source_gaps'] == [{'task_id': 'trace', 'need': 'GUIDE'}]
    assert 'facts' in feedback['repair_note'] and '{{FIELD}}' in feedback['repair_note']
    assert source.calls == [('get_shipment_trace', {}), ('get_support_guide', {})]
    assert result['spend']['model_calls'] == 5
