#!/usr/bin/env python
"""Create one local, reviewable synthetic refund case without approving or paying it.

Commerce has no public order-creation route, so the existing e2e fixture helper mints
the paid order line. All case, evidence, verification and proposal writes use the
authenticated core API. The proposal is HUMAN-origin and must be shown as such.
Run only against the local core demo stack; this is not a live-model evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import e2e_harness_java_tools as tools
import e2e_refund_chain as chain
import e2e_transport_refund as base

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from resolveflow.policies.index import PolicyIndex  # noqa: E402
from resolveflow.policies.retrieval import embedder  # noqa: E402
from resolveflow.runtime.db import Database  # noqa: E402

GATEWAY = "http://127.0.0.1:8080"
AMOUNT_MINOR = 32900
DESCRIPTION = (
    "包裹发货后多日未送达，物流一直没有签收记录；承运商现已确认丢失。"
    "商品未收到，申请退还该订单行已支付金额。"
)
CUSTOMER_EVIDENCE = (
    "物流页面持续显示运输异常，未出现签收记录。我联系承运商后获知包裹已判定丢失，"
    "目前仍未收到商品。"
)
VERIFICATION = (
    "已核对本地合成物流记录：承运商结论为 LOST，只有丢失事件，未见签收事件；"
    "与客户陈述一致。"
)
PROPOSAL_REASON = (
    "合成物流记录显示承运商确认丢失且无签收；客户陈述已由审核员核验。"
    "依据钉住的物流丢失政策，由 Case 服务端重算本订单行可退金额，提交全额退款授权供人工决定。"
)


def api(path: str, *, token: str | None = None, body: dict | None = None,
        headers: dict[str, str] | None = None) -> dict:
    status, result = tools.request_json(
        GATEWAY + path, method="POST" if body is not None else "GET",
        token=token, body=body, headers=headers)
    expected = 201 if path == "/api/v1/cases" else 200
    if status != expected or not isinstance(result, dict):
        raise RuntimeError(f"{path} returned {status}: {result}")
    return result


def synthetic_headers(case_id: str, token: str, version: int) -> dict[str, str]:
    ownership = api(f"/api/v1/cases/{case_id}/collaboration", token=token)
    if ownership["owner"] is None:
        ownership = api(f"/api/v1/cases/{case_id}/collaboration", token=token,
                        headers={"If-Collaboration-Match": f'"{ownership["version"]}"'},
                        body={"action": "CLAIM", "reason": "合成展示：领取本次工单"})
    if not ownership["is_owner"]:
        raise RuntimeError("showcase case belongs to another staff member; transfer explicitly")
    return {"If-Match": f'"{version}"', "If-Collaboration-Match": f'"{ownership["version"]}"'}


def citation(record: dict) -> dict[str, str]:
    return {key: record[key] for key in
            ("observation_id", "source_ref", "source_version", "content_hash")}


def pinned_lost_policy(case_id: str) -> dict[str, str]:
    rows = base.mysql_rows(
        "SELECT cp.bundle_id,pm.manifest_hash FROM case_db.case_policy_bundle cp "
        "JOIN case_db.case_policy_manifest pm ON pm.case_id=cp.case_id "
        f"WHERE cp.case_id='{case_id}'")
    if len(rows) != 1:
        raise RuntimeError(f"expected one pinned policy bundle, got {len(rows)}")
    bundle_id, manifest_hash = rows[0]
    database = Database()
    try:
        hits = PolicyIndex(database).search(
            merchant_id="M-1001", bundle_ids=[bundle_id], manifest_hash=manifest_hash,
            query="物流丢失 全额退款", path="dense", top_k=5, embedder=embedder())
    finally:
        database.close()
    rule = next((hit for hit in hits if hit.rule_id == "R-LOST-001"), None)
    if rule is None:
        raise RuntimeError("the pinned lost-parcel rule was absent from the local policy index")
    return {key: getattr(rule, key) for key in
            ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-case", help="complete a previously created showcase case")
    args = parser.parse_args()
    if api("/actuator/health").get("status") != "UP" or base.mysql_rows("SELECT 1") != [["1"]]:
        raise RuntimeError("local gateway or MySQL is unavailable")
    output = ROOT / "tmp" / "frontend-review-showcase"
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report = base.Report(output / f"{stamp}-result.txt")
    report.head("# Local synthetic review showcase; HUMAN proposal, no refund execution")

    customer = api("/api/v1/auth/login", body={"username": tools.CUSTOMER,
                                               "password": tools.CUSTOMER_PASSWORD})["access_token"]
    reviewer = api("/api/v1/auth/login", body={"username": "demo-reviewer",
                                               "password": "demo-pass-1003"})["access_token"]
    if args.resume_case:
        case_id = str(uuid.UUID(args.resume_case))
        view = api(f"/api/v1/cases/{case_id}", token=reviewer)
        line_id = view["case"]["line_id"]
        report.note(f"resuming case={case_id} line={line_id}; no new fixture rows")
        if view.get("authorization", {}).get("status") == "PENDING_REVIEW":
            if (view.get("proposal", {}).get("origin") != "HUMAN"
                    or view["proposal"].get("status") != "VALIDATED"
                    or view["proposal"].get("recomputed_amount_minor") != AMOUNT_MINOR):
                raise RuntimeError("existing pending authorization is not the expected showcase proposal")
            report.note("showcase already complete; no additional proposal submitted")
            report.finish("PASSED")
            print(json.dumps({"case_id": case_id, "line_id": line_id,
                              "amount_minor": AMOUNT_MINOR,
                              "report": str(output / f"{stamp}-result.txt")}, ensure_ascii=False))
            return 0
    else:
        line_id, _, _ = chain.create_demo_line(AMOUNT_MINOR, report)
        now = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")
        base.mysql_rows(
            "START TRANSACTION;"
            " INSERT INTO commerce_db.shipment (line_id,status,carrier_conclusion,source_version)"
            f" VALUES ('{line_id}','LOST','LOST',1);"
            " INSERT INTO commerce_db.shipment_event (line_id,code,occurred_at,source_version)"
            f" VALUES ('{line_id}','CARRIER_LOST','{now}',1); COMMIT;")
        created = api("/api/v1/cases", token=customer,
                      headers={"Idempotency-Key": f"frontend-showcase-{line_id}"},
                      body={"line_id": line_id, "description": DESCRIPTION,
                            "requested_actions": ["REFUND"]})
        case_id = str(uuid.UUID(created["case_id"]))
        api(f"/api/v1/cases/{case_id}/evidence", token=customer,
            body={"text": CUSTOMER_EVIDENCE, "evidence_kind": "CUSTOMER_STATEMENT"})
        view = api(f"/api/v1/cases/{case_id}", token=reviewer)
        statement = next(item for item in view["evidence"] if item["evidence_kind"] == "CUSTOMER_STATEMENT")
        api(f"/api/v1/cases/{case_id}/reviewed-evidence", token=reviewer,
            headers=synthetic_headers(case_id, reviewer, view["case"]["version"]),
            body={"source_evidence_id": statement["observation_id"],
                  "verification_result": "CONFIRMED", "reason": VERIFICATION})
    view = api(f"/api/v1/cases/{case_id}", token=reviewer)
    statement = next(item for item in view["evidence"] if item["evidence_kind"] == "CUSTOMER_STATEMENT")
    verification = next(item for item in view["evidence"]
                        if item["evidence_kind"] == "REVIEWER_VERIFICATION")
    policy = pinned_lost_policy(case_id)
    api(f"/api/v1/cases/{case_id}/manual-proposals", token=reviewer,
        headers=synthetic_headers(case_id, reviewer, view["case"]["version"]),
        body={"action": "REFUND", "reason": PROPOSAL_REASON,
              "evidence_refs": [citation(statement), citation(verification)],
              "policy_refs": [policy]})

    final = api(f"/api/v1/cases/{case_id}", token=reviewer)
    assert final["case"]["status"] == "PENDING_REVIEW"
    assert final["proposal"]["origin"] == "HUMAN"
    assert final["proposal"]["status"] == "VALIDATED"
    assert final["proposal"]["recomputed_amount_minor"] == AMOUNT_MINOR
    assert final["authorization"]["status"] == "PENDING_REVIEW"
    assert len(final["evidence"]) == 2
    report.note(f"case={case_id} line={line_id} amount_minor={AMOUNT_MINOR}")
    report.note("customer material=1 reviewer verification=1 pinned policy=R-LOST-001")
    report.note("proposal=HUMAN/VALIDATED authorization=PENDING_REVIEW; approval and refund not executed")
    report.finish("PASSED")
    print(json.dumps({"case_id": case_id, "line_id": line_id, "amount_minor": AMOUNT_MINOR,
                      "report": str(output / f"{stamp}-result.txt")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
