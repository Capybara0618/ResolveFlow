import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import jev_compare as study


def test_cohort_is_all_existing_single_turns_and_labels_are_not_sources():
    fixture = json.loads(study.FIXTURE.read_bytes())
    assert len(fixture["cases"]) == 19
    for case in fixture["cases"]:
        sources = study.FrozenSources(case)
        assert "criteria" not in json.dumps(sources.search("任意问题", 3), ensure_ascii=False)
        assert all(p["data"]["bundle_id"] in case["request"]["context"]["policy_manifest"]["bundle_ids"]
                   for p in sources.search("另一种说法", 1))


def test_source_failures_do_not_become_empty_successes():
    case = {"http_status": {"get_shipment_trace": 503}, "facts": {}}
    assert study.FrozenSources(case).read("get_shipment_trace", {}) == {
        "error": "SOURCE_UNAVAILABLE", "retryable": True}
    assert study.FrozenSources(case).read("get_order_context", {}) == {
        "error": "NOT_FOUND", "retryable": False}


def test_allowance_is_saved_before_call_and_refuses_exhaustion(tmp_path):
    budget = study.Allowance(tmp_path)
    path, record = budget.reserve("baseline", {"model": "test", "max_tokens": 1024})
    assert json.loads(path.read_bytes())["status"] == "STARTED"
    assert "Authorization" not in record["request"]
    budget.calls = 300
    with pytest.raises(study.SupportFailure, match="STUDY_ALLOWANCE_EXHAUSTED"):
        budget.reserve("jev", {})


def test_cost_cap_cannot_be_bypassed_by_large_input(tmp_path):
    budget = study.Allowance(tmp_path)
    with pytest.raises(study.SupportFailure, match="STUDY_ALLOWANCE_EXHAUSTED"):
        budget.reserve("baseline", {"text": "大" * 2_000_000})
    assert not list(tmp_path.glob("attempt-*.json"))


def test_freeze_is_immutable_and_execute_needs_explicit_live(tmp_path, monkeypatch):
    output = tmp_path / "new-study"
    study.freeze(output)
    with pytest.raises(FileExistsError):
        study.freeze(output)
    monkeypatch.setattr(sys, "argv", ["jev_compare", "execute", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        study.main()
    assert error.value.code == 2


@pytest.mark.parametrize("citation,expected", [("O2", "SUCCEEDED"), ("O999", "FAILED")])
def test_revision_must_pass_current_harness_with_no_network(citation, expected):
    from tests.unit.test_support_agent import read
    from tests.unit.test_support_orchestrated_engine import respond
    from tests.unit.test_support_orchestration import plan

    case = json.loads(study.FIXTURE.read_bytes())["cases"][0]
    value = case["request"] | {"deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=60)}
    req = study.SupportInput.model_validate(value)
    opening = plan(req, intent="LOGISTICS", goal="EXPLAIN", needs=["SHIPMENT"]).model_dump()
    final = respond(parts=[{"task_id": "trace", "text": "物流显示已签收。", "citations": [citation]}],
                    refund_reason=None)
    originals = [{"decision": opening}, {"decision": read()}, {"decision": final}]
    result = study.validate_revision(req, case, originals, final)
    assert result["status"] == expected
