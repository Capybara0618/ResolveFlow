"""Offline verification of original refund fault evidence; never requests refunds."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from cohort import load

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.contracts.core_corpus import core_signing_keys, load_core_corpus
from resolveflow.contracts.events import verify_core_envelope


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(raw):
    _manifest, records, lineage = load(raw)
    public = core_signing_keys(load_core_corpus())[1]
    counts, orders, lines, operations, cases = Counter(), [], [], [], []
    recovery = {scenario: [] for scenario in ("F04", "F05", "F07")}
    case_for_op = {}
    amount_for_line = {}
    extra_reconciliation = []
    confounded_windows = []
    for spec, row, folder, failed in records:
        assert spec["id"] == row["id"] and row["scenario"] == spec["scenario"]
        if not failed:
            saved = read(folder / "outcome.json")
            for name, digest in saved["evidence"].items():
                assert sha(folder / name) == digest
            assert {k: v for k, v in saved.items() if k != "evidence"} == row
        entity = row["entities"]
        scenario = spec["scenario"]
        size = 2 if scenario == "F03" else 1
        counts[scenario] += 1
        assert len(entity["lines"]) == len(entity["operations"]) == len(entity["cases"]) == size
        orders.append(entity["order_id"])
        lines += entity["lines"]
        operations += entity["operations"]
        cases += entity["cases"]
        case_for_op.update(zip(entity["operations"], entity["cases"], strict=True))
        purchase = read(folder / "purchase.json")
        assert purchase["order_id"] == entity["order_id"] and purchase["total_amount"] == entity["amount"]
        assert sum(line["line_amount"] for line in purchase["lines"]) == entity["amount"]
        amount_for_line.update({line["line_id"]: line["line_amount"] for line in purchase["lines"]})
        if scenario == "F03":
            assert sorted(line["line_amount"] for line in purchase["lines"]) == [19900, 32900]
        for stage in ("before-approval", "reserved", "settled"):
            snapshot_path = folder / (stage + ".json")
            if failed and not snapshot_path.exists():
                assert spec["id"] == "F07-r06" and stage in ("reserved", "settled")
                continue
            snapshot = read(snapshot_path)
            assert snapshot["paid"] == entity["amount"]
            assert snapshot["refunded"] >= 0 and snapshot["reserved"] >= 0
            assert snapshot["refunded"] + snapshot["reserved"] <= snapshot["paid"]
            if stage == "reserved":
                assert snapshot["refunded"] == 0 and snapshot["reserved"] == entity["amount"]
        original = read(folder / "original-commands.json")
        for envelope in original:
            verify_core_envelope(envelope, envelope["signature"], public)
        trace_path = folder.parent.parent / "provider-http.jsonl"
        trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
                 if json.loads(line)["operation_id"] in entity["operations"]]
        if scenario != "F04" and any(item["stage"] == "query" for item in trace):
            gate_durations = []
            for op in entity["operations"]:
                requests = [t["monotonic"] for t in trace if t["operation_id"] == op and t["stage"] == "request"]
                receipts = [t["monotonic"] for t in trace if t["operation_id"] == op and t["stage"] == "receipt"]
                if requests and receipts:
                    gate_durations.append(receipts[0] - requests[0])
            extra_reconciliation.append({"round": spec["id"], "gate_seconds": gate_durations,
                                         "reason": "unplanned reconciliation; gate duration compared with production 5-second read timeout"})
        if failed:
            diagnostic = read(folder.parent.parent / "failed-window-readonly-diagnostic.json")
            assert diagnostic["sent_on_audit"] == 0
            assert diagnostic["diagnostic"]["operation"]["operation_id"] == entity["operations"][0]
            assert diagnostic["diagnostic"]["operation"]["state"] == "SUCCEEDED"
            assert diagnostic["diagnostic"]["result_outbox"][0]["status"] == "PUBLISHED"
            assert diagnostic["diagnostic"]["case"]["status"] == "CLOSED_SUCCESS"
            if scenario == "F07":
                start, window = read(folder / "broker-stopped.json"), read(folder / "broker-window.json")
                assert start["pids"] == window["pids"] and window["stopped_seconds"] >= 10
                assert window["command_status"] == "PENDING" and window["no_operation_before_recovery"]
            continue
        final = row["final"]
        trace = final["provider_http"]
        assert final["paid"] == final["refunded"] == entity["amount"] and final["reserved"] == 0
        assert final["operation_count"] == size
        assert final["closed_events"] == final["provider_successes"] == final["provider_attempts"] == [1] * size
        assert final["operation_states"] == ["SUCCEEDED"] * size
        assert final["line_states"] == ["CONSUMED"] * size and final["case_states"] == ["CLOSED_SUCCESS"] * size
        assert all(op["provider_key"] == op["operation_id"] for op in final["operations"])
        original = read(folder / "original-commands.json")
        for envelope in original:
            verify_core_envelope(envelope, envelope["signature"], public)
        if scenario in ("F01", "F02"):
            sent, acks, received = (read(folder / name) for name in
                                   ("commands-sent.json", "commands-sent-acks.json", "consumer-receipts.json"))
            assert len(sent) == len(acks) == len(received) == 10
            assert {a["message_id"] for a in acks} == set(received)
            assert all(a["status"] == "SEND_OK" for a in acks)
            assert Counter(received.values()) == {"ACCEPTED": 1, "DUPLICATE": 9}
            envelopes = [json.loads(item["envelope"]) for item in sent]
            for envelope in envelopes:
                verify_core_envelope(envelope, envelope["signature"], public)
                assert envelope["payload"] == original[0]["payload"]
            assert len({e["event_id"] for e in envelopes}) == (1 if scenario == "F01" else 10)
        if scenario == "F04":
            early, later = read(folder / "unknown.json"), read(folder / "unknown-after-visibility-window.json")
            for snapshot in (early, later):
                assert snapshot["refunded"] == 0 and snapshot["reserved"] == entity["amount"]
                assert snapshot["operations"][0]["state"] == "UNKNOWN"
                assert snapshot["operations"][0]["operation_id"] == entity["operations"][0]
                assert snapshot["operations"][0]["provider_key"] == entity["operations"][0]
            assert later["monotonic"] >= later["visible_monotonic"]
            trace = final["provider_http"]
            assert sum(item["stage"] == "request" for item in trace) == 1
            lost = [item for item in trace if item["stage"] == "socket_lost"]
            assert len(lost) == 1 and lost[0]["visibility_delay_seconds"] == 10
            requested_at = next(item["monotonic"] for item in trace if item["stage"] == "request")
            # This planned loss must occur before the production client's 5-second timeout;
            # unrelated gate timeouts in other scenarios are retained separately.
            loss_seconds = lost[0]["monotonic"] - requested_at
            if loss_seconds >= 5:
                assert spec["id"] == "F04-r10"
                confounded_windows.append({"round": spec["id"], "loss_after_request_seconds": loss_seconds,
                    "classification": "planned socket loss masked by earlier 5-second client timeout"})
            assert any(item["stage"] == "query" and item["state"] == "SUCCEEDED"
                       and item["monotonic"] >= lost[0]["visible_monotonic"] for item in trace)
        if scenario == "F05":
            pending, restarted = read(folder / "unpublished-before-kill.json"), read(folder / "commerce-restarted.json")
            assert pending["status"] == "PENDING" and pending["event_id"] == final["results"][0]["event_id"]
            assert pending["pid"] == restarted["old_pid"] != restarted["new_pid"]
        if scenario == "F06":
            sent = read(folder / "results-sent.json")
            assert len(sent) == 9 and len({item["event_id"] for item in sent}) == 1
            assert sent[0]["event_id"] == final["results"][0]["event_id"]
            for item in sent:
                verify_core_envelope(json.loads(item["envelope"]), json.loads(item["envelope"])["signature"], public)
        if scenario == "F07":
            start, window = read(folder / "broker-stopped.json"), read(folder / "broker-window.json")
            assert start["pids"] == window["pids"] and window["stopped_seconds"] >= 10
            assert window["command_status"] == "PENDING" and window["no_operation_before_recovery"]
            assert final["commands"][0]["status"] == "PUBLISHED"
        if scenario in recovery:
            assert 0 <= row["recovery_seconds"] <= 120
            if spec["id"] not in {item["round"] for item in confounded_windows}:
                recovery[scenario].append(row["recovery_seconds"])
    assert counts == {f"F{i:02d}": 10 for i in range(1, 8)}
    assert len(orders) == len(set(orders)) == 70
    assert len(lines) == len(set(lines)) == len(operations) == len(set(operations)) == len(cases) == len(set(cases)) == 80
    database = read(raw / "refund-formal-final-database.json")
    assert database["new_operations"] == database["new_success_operations"] == database["new_provider_successes"] == sorted(operations)
    assert len(database["operations"]) == len(database["provider"]) == 80
    unknown = database["nonconverging_control"]
    assert unknown["operation"]["state"] == "UNKNOWN" and unknown["ledger"]["reserved"] == 32900
    assert unknown["ledger"]["refunded"] == 0 and not unknown["provider_receipts"]
    assert unknown["operation"]["provider_key"] == unknown["operation"]["operation_id"]
    for row in database["operations"]:
        assert row["operation_id"] in operations and row["case_id"] == case_for_op[row["operation_id"]]
        assert row["state"] == "SUCCEEDED" and row["authorization_status"] == "CONSUMED"
        assert row["case_status"] == "CLOSED_SUCCESS" and row["amount_minor"] == amount_for_line[row["line_id"]]
        assert row["operation_revision"] == row["authorization_revision"] == row["case_revision"]
        assert row["command_count"] == row["result_count"] == row["closed_events"] == 1
        assert row["paid"] == row["refunded"] and row["reserved"] == 0 and row["line_state"] == "CONSUMED"
        if row["operation_id"] in {r["entities"]["operations"][0] for _, r, _, failed in records if r["scenario"] == "F06" and not failed}:
            assert row["success_result_deliveries"] >= 10
    for row in database["provider"]:
        assert row["successes_per_line"] == row["processing_attempts"] == row["requests"] == 1
        assert row["state"] == "SUCCEEDED" and row["operation_id"] in operations
        assert row["amount_minor"] == amount_for_line[row["line_id"]]
    assert len(confounded_windows) == 1
    return {**lineage, "formal_rounds": 70, "runner_passed": 68, "validated_fault_windows": 67, "confounded_windows": confounded_windows, "scenarios": dict(counts), "successful_refund_lines": 80,
            "successful_orders": 70, "successful_operations": 80, "provider_successes": 80,
            "duplicate_refunds": 0, "over_refunded_orders": 0, "excess_reservations_at_sampled_boundaries": 0,
            "recovery_seconds": {key: {"observations": len(values), "min": min(values), "max": max(values),
                                      "mean": sum(values) / len(values)} for key, values in recovery.items()},
            "model_requests": 0, "unknown_control_reserved_minor": 32900,
            "additional_reconciliation_rounds": extra_reconciliation,
            "boundary": "sampled ledger boundaries plus final global audit; synthetic provider, one local instance"}


if __name__ == "__main__":
    result = audit(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("xb") as output:
        output.write((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(result))
