"""One invalid source annotation must not hide independent missing answer sources."""

import json

from resolveflow.support.guide import guide_source
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_staged import staged, understand


class Sources(FactReads):
    def read(self, name, arguments):
        if name == "get_support_guide":
            self.calls.append((name, arguments))
            return guide_source()
        return super().read(name, arguments)


def response(refs, guide):
    piece = part("trace", "请结合订单和物流核实申请原因。", refs)
    piece["facts"] = [{"field": "SHIPMENT_STATUS", "source": "O1"}]
    piece["next_steps"] = [{"action": "REFUND_APPLICATION", "source": guide}]
    return {**parts(piece), "fact_rendering": "fields-v1"}


def test_wrong_guide_feedback_lists_order_and_guide_before_the_only_repair():
    req = request()
    bad = response(["O1"], "O1")
    good = response(["O1", "O3"], "O2")
    result, model, source, agent = staged(req, [
        understand(req, intent="APPLICATION", needs=["SHIPMENT", "ORDER", "GUIDE"]), read(), bad,
        read("get_support_guide"), read("get_order_context"), good], Sources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[3]["feedback"])
    assert len(feedback["source_gaps"]) == 2
    assert {g["need"] for g in feedback["source_gaps"]} == {"ORDER", "GUIDE"}
    assert all(g["task_id"] == "trace" for g in feedback["source_gaps"])
    assert feedback["required_read"]["tool_name"] == "get_support_guide"
    assert "全部" in feedback["repair_note"]
    assert model.calls == 6 and agent.repairs == 1 and len(source.calls) == 3
    assert model.packets[3]["task_state"]["tasks"][0]["status"] == "PENDING"


def test_valid_fact_source_without_literal_citation_is_counted_in_metadata_diagnostics():
    req = request()
    bad = response([], "O1")
    good = response(["O3"], "O2")
    result, model, _, _ = staged(req, [
        understand(req, intent="APPLICATION", needs=["SHIPMENT", "ORDER", "GUIDE"]), read(), bad,
        read("get_support_guide"), read("get_order_context"), good], Sources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[3]["feedback"])
    assert {g["need"] for g in feedback["source_gaps"]} == {"ORDER", "GUIDE"}


def test_independent_valid_guide_survives_a_different_invalid_step_in_diagnostics():
    req = request()
    bad = response(["O1"], "O99")
    bad["parts"][0]["next_steps"].append({"action": "MERCHANT_REVIEW", "source": "O2"})
    good = response(["O1", "O3"], "O2")
    result, model, _, _ = staged(req, [
        understand(req, intent="APPLICATION", needs=["SHIPMENT", "ORDER", "GUIDE"]), read(),
        read("get_support_guide"), bad, read("get_order_context"), good], Sources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert json.loads(model.packets[4]["feedback"])["source_gaps"] == [{"task_id": "trace", "need": "ORDER"}]
