"""Immutable v3 projection fork; production rejects the preserved v2 malformed sources."""

import shutil
from pathlib import Path

from resolveflow.tools.result_validation import InvalidToolResult, validate_result
from scripts.evaluation.build_alignment import write
from scripts.evaluation.dataset import ALIGNED_DATA, ROOT, digest, read

CALIBRATED_DATA = ROOT / "evals/calibrated-v3"


def validate_projection(case):
    backend = case["backend"]
    for tool, source in (("get_order_context", "order"), ("get_shipment_trace", "shipment"),
                         ("get_refund_status", "refund"), ("get_case_evidence", "evidence")):
        if backend.get("errors", {}).get(tool, 200) != 200:
            continue
        body = backend[source]
        if source == "refund":
            body = {**{key: backend["order"][key] for key in
                       ("merchant_id", "line_paid_amount", "currency")}, **body}
        validate_result(tool, body, line_id=case["scope"]["line_id"], case_id=case["case_id"])


def build(directory: Path = CALIBRATED_DATA):
    if directory.exists():
        raise ValueError("Calibration dataset is immutable; choose a new directory")
    parent = read("manifest.json", ALIGNED_DATA)
    cases = read("agent/cases.json", ALIGNED_DATA)
    gold = read("gold/agent.json", ALIGNED_DATA)
    negative = []
    for name in parent["files"]:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ALIGNED_DATA / name, target)
    for case in cases:
        try:
            validate_projection(case)
        except InvalidToolResult as error:
            from copy import deepcopy
            negative.append({"id": case["id"], "original_case": deepcopy(case),
                             "expected_error": "TOOL_RESULT_INVALID", "contract_detail": str(error)})
        if case["id"] in {"A03B", "A07B", "A16B"}:
            # UNKNOWN/IN_PROGRESS belongs to refund_operation, not to the line slot.
            case["backend"]["order"]["line_refund_state"] = "RESERVED"
            case["backend"]["refund"]["state"] = "RESERVED"
        if case["id"] == "A04B":
            # CheckoutPayments materializes orders/order_line only on successful payment.
            # This is an injected pre-Java-boundary probe, not a normal dispatched refund.
            order = case["backend"]["order"]
            case["backend"]["order"] = {k: order[k] for k in
                                         ("order_id", "line_id", "merchant_id", "customer_id")}
            case["backend"]["errors"] = {"get_order_context": 404, "get_shipment_trace": 404,
                                          "get_refund_status": 404}
            gold[case["id"]] = {**gold[case["id"]], "must_tools": [],
                                "must_read_errors": [{"tool": "get_order_context", "code": "NOT_FOUND"}]}
        if case["backend"]["shipment"].get("carrier_conclusion") == "SIGNED":
            case["backend"]["shipment"]["carrier_conclusion"] = "DELIVERED"
        validate_projection(case)
    write(directory / "agent/cases.json", cases)
    write(directory / "gold/agent.json", gold)
    write(directory / "harness/malformed-v2.json", negative)
    files = {name: digest(directory / name) for name in [*parent["files"], "harness/malformed-v2.json"]}
    write(directory / "manifest.json", {
        **parent, "version": "resolveflow-evaluation-calibrated-v3", "created": "2026-10-05", "files": files,
        "parent_manifest_sha256": digest(ALIGNED_DATA / "manifest.json"),
        "projection_profile": "core-java-read-projection-v1",
        "changes": ["three held slots use RESERVED, not operation status",
                    "SIGNED carrier conclusions use core DELIVERED, not a fictitious carrier enum",
                    "A04B is an unpaid draft source-missing boundary probe, all line reads 404",
                    "A04B Gold requires the observed NOT_FOUND, not an impossible successful line read",
                    "all original malformed sources retained as negative contract tests"],
        "unchanged": "32 ids/pairs/splits, allowed/forbidden actions, other Gold, all policies/RAG queries",
        "case_population": {"normal_synthetic_cases": 31, "pre_java_boundary_probes": ["A04B"]},
    })
    # Dataset calibration lineage is separate from current-code strict replay.
    for path in (ALIGNED_DATA / "replay/golden").rglob("*"):
        if path.is_file():
            target = directory / path.relative_to(ALIGNED_DATA)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    replay_files = {path.relative_to(directory).as_posix(): digest(path)
                    for path in (directory / "replay/golden").rglob("*") if path.is_file()}
    write(directory / "replay/manifest.json", {
        "dataset_manifest_sha256": digest(directory / "manifest.json"), "files": replay_files,
        "purpose": "unchanged v2 calibration lineage; not current-source strict replay"})
    return directory


if __name__ == "__main__":
    build()
