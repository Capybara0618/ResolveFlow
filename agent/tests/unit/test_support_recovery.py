from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request


class Unavailable(Reads):
    def read(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_support_guide":
            return {"source_type": "KNOWLEDGE", "version": "v1",
                    "data": {"authority": "APPLICATION_GUIDE", "text": "可预览摘要后确认请商家核查。"}}
        return {"error": "SOURCE_UNAVAILABLE", "retryable": True}


def test_repeated_outage_stops_network_reads_but_allows_guide_and_honest_answer():
    source = Unavailable()
    model = MockModelClient(script=[
        read(), read(), read(), read("get_support_guide"),
        answer(text="物流查询暂不可用，可预览摘要后确认请商家核查。", citations=["O1"]),
    ])
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert [name for name, _ in source.calls].count("get_shipment_trace") == 2
    state = model.packets[2]["source_status"][0]
    assert state["retry_allowed"] is False and state["failures"] == 2
    assert model.packets[3]["observations"][-1]["error"] == "SOURCE_RETRY_EXHAUSTED"
    assert "get_support_guide" in model.packets[2]["capabilities"]


def test_transient_outage_can_recover_without_blocking_later_facts():
    class Recovers(Reads):
        def read(self, name, arguments):
            if not self.calls:
                self.calls.append((name, arguments))
                return {"error": "SOURCE_UNAVAILABLE", "retryable": True}
            return super().read(name, arguments)

    model = MockModelClient(script=[read(), read(), answer(citations=["O1"])])
    assert SupportAgent(request(), model, Recovers()).run()["status"] == "SUCCEEDED"
    assert model.packets[1]["source_status"][0]["retry_allowed"] is True
    assert model.packets[2]["source_status"] == []


def test_nonretryable_source_error_is_not_called_again():
    class Refused(Unavailable):
        def read(self, name, arguments):
            self.calls.append((name, arguments))
            return {"error": "NOT_FOUND", "retryable": False}

    source = Refused()
    model = MockModelClient(script=[read(), read(), answer(citations=[], text="没有取得记录，请商家核查。")])
    assert SupportAgent(request(), model, source).run()["status"] == "SUCCEEDED"
    assert len(source.calls) == 1
