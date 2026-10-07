"""Fork synthetic inputs to match CheckoutPayments' NOT_SHIPPED/UNKNOWN initial shipment."""

import copy
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from scripts.evaluation.build_calibration import validate_projection
from scripts.evaluation.dataset import digest, read, validate


def corrected_cases(cases):
    result, changed = copy.deepcopy(cases), []
    for case in result:
        backend = case["backend"]
        shipment = backend["shipment"]
        if (
            backend["order"].get("fulfillment_status") == "NOT_SHIPPED"
            and shipment.get("status") == "IN_TRANSIT"
            and shipment.get("carrier_conclusion") == "IN_TRANSIT"
            and not shipment.get("events")
            and not backend.get("errors", {}).get("get_shipment_trace")
        ):
            shipment.update(status="NOT_SHIPPED", carrier_conclusion="UNKNOWN")
            changed.append(case["id"])
    return result, changed


def main():
    source = ROOT / "evals/calibrated-v3"
    output = ROOT / "evals/resume-quantification-v1/business-v1"
    if output.exists():
        raise FileExistsError("immutable input fork")
    validate(source)
    cases, changed = corrected_cases(read("agent/cases.json", source))
    if len(changed) != 5:
        raise ValueError("unexpected calibration population")
    for case in cases:
        validate_projection(case)
    shutil.copytree(source, output)
    readme = output / "README.md"
    historical = readme.read_text(encoding="utf-8").replace(
        "# 契约校准评测 v3", "## 父版本历史说明", 1
    )
    readme.write_text(
        "# 简历量化业务输入 v1\n\n"
        "从calibrated-v3不可变分叉；只将5个明确未发货、无事件、无读取错误的合成默认物流改为NOT_SHIPPED/UNKNOWN，匹配实际CheckoutPayments初始投影。具体字段、案例及parent SHA见manifest.json，所有Gold字节、政策/RAG和32例配对保持。\n\n"
        "当前strict回放沿独立decision-handoff-v14的18包；本目录复制的replay文件仅历史血缘。生成器为scripts/resume_agent_inputs.py，试跑与正式结果见reports/resume-quantification-v1/agent。以下保留父版本的历史校准说明，旧strict路径不作为本轮入口。\n\n"
        + historical,
        encoding="utf-8",
        newline="\n",
    )

    def write(path, value):
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    write(output / "agent/cases.json", cases)
    manifest = read("manifest.json", source)
    manifest.update(
        version="resume-business-v1",
        created="2026-10-07",
        parent_manifest_sha256=digest(source / "manifest.json"),
        changes=[
            {
                "ids": changed,
                "fields": [
                    "backend.shipment.status",
                    "backend.shipment.carrier_conclusion",
                ],
                "before": ["IN_TRANSIT", "IN_TRANSIT"],
                "after": ["NOT_SHIPPED", "UNKNOWN"],
                "reason": "empty synthetic default contradicted explicit NOT_SHIPPED fulfillment; match CheckoutPayments initial shipment projection",
            }
        ],
        unchanged="all Gold bytes, ids/pairs/splits, order/refund/material facts, policies/RAG queries, actual conflict/error/occupied scenarios",
    )
    manifest["files"]["agent/cases.json"] = digest(output / "agent/cases.json")
    write(output / "manifest.json", manifest)
    replay = read("replay/manifest.json", source)
    replay.update(
        dataset_manifest_sha256=digest(output / "manifest.json"),
        purpose="unchanged calibrated-v3 historical fixture lineage; not current-source strict replay",
    )
    write(output / "replay/manifest.json", replay)
    print(validate(output), "corrected", changed)


if __name__ == "__main__":
    main()
