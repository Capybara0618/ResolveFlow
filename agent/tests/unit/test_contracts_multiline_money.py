"""Current core money facts distinguish the order ledger from each whole-line slot."""
import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator
from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import extract_facts
from resolveflow.harness.facts import FactsView

FIXTURES = json.loads((REPO_ROOT / "contracts/core/fixtures/multiline-money.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", FIXTURES, ids=lambda sample: sample["name"])
def test_current_money_fixture_and_original_optional_contract(sample: dict) -> None:
    validator = component_validator("commerce", sample["schema"], "contracts/core")
    assert validator.accepts(sample["value"]), validator.error_messages(sample["value"])


def observed(value: dict) -> ToolObservation:
    return ToolObservation(observation_id="multi-line-money", tool_name="get_refund_status",
                           source_type=EvidenceSourceType.PAYMENT_LEDGER,
                           source_ref="commerce:/internal/v1/order-lines/line-b/refund-status",
                           source_version="3", content_hash="a" * 64, observed_at="2026-10-03T04:00:00Z",
                           result=value)


def test_current_facts_do_not_misattribute_another_lines_money() -> None:
    body = next(s["value"] for s in FIXTURES if s["name"] == "another-line-refunded-status")
    facts = {f.key: f.value for f in extract_facts(FactsView(), observed(body))}
    assert facts["line_refunded_amount_minor"] == "0"
    assert facts["line_reserved_amount_minor"] == "0"
    assert facts["order_refunded_amount_minor"] == "32900"
    assert facts["payment_order_paid_amount_minor"] == "72700"
    assert facts["line_refund_state"] == "FREE"


def test_missing_current_line_amounts_cannot_fall_back_to_order_totals() -> None:
    body = copy.deepcopy(next(s["value"] for s in FIXTURES if s["name"] == "another-line-refunded-status"))
    del body["line_refunded_amount"]
    facts = {f.key: f.value for f in extract_facts(FactsView(), observed(body))}
    assert "line_refunded_amount_minor" not in facts
    assert facts["order_refunded_amount_minor"] == "32900"


def test_new_core_members_remain_strict_and_do_not_allow_scope_or_money_overrides() -> None:
    sample = FIXTURES[0]
    validator = component_validator("commerce", sample["schema"], "contracts/core")
    for key, value in [("line_refund_state", "UNKNOWN"), ("order_paid_amount", -1), ("client_amount", 1)]:
        bad = {**sample["value"], key: value}
        assert not validator.accepts(bad)
