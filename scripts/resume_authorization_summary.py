"""Recompute immutable authorization measurements and bind their source files."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/resume-quantification-v1/authorization"


def main() -> None:
    files = sorted((REPORT / "attempt2").glob("*.json"))
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    scenarios = [row for row in rows if row["scenario"].startswith("V")]
    consumed = [row for row in rows if row["scenario"] == "consume-wins"]
    assert len(scenarios) == 80 and len(consumed) == 10
    assert {
        key: sum(row["scenario"] == key for row in scenarios)
        for key in (f"V{i}" for i in range(1, 9))
    } == {f"V{i}": 10 for i in range(1, 9)}
    totals = {
        key: sum(row[key] for row in scenarios)
        for key in (
            "expired_attempts",
            "expired_rejected",
            "illegal_consumptions",
            "valid_consumptions",
        )
    }
    assert totals == {
        "expired_attempts": 90,
        "expired_rejected": 90,
        "illegal_consumptions": 0,
        "valid_consumptions": 80,
    }
    assert all(row["update_rejected"] for row in consumed)
    tests = {}
    for name in ("ResumeAuthorizationMatrixApiTest", "ReviewQueueBackpressureTest"):
        junit = ROOT / (
            "java/case-service/target/surefire-reports/TEST-"
            f"com.resolveflow.caseservice.casefile.{name}.xml"
        )
        tests[name] = {
            key: ElementTree.parse(junit).getroot().attrib[key]
            for key in ("tests", "failures", "errors", "skipped", "time")
        }
        assert all(tests[name][key] == "0" for key in ("failures", "errors", "skipped"))
    sources = [
        Path("scripts/resume_authorization_summary.py"),
        Path(
            "java/case-service/src/main/java/com/resolveflow/caseservice/casefile/ReviewQueueService.java"
        ),
    ]
    sources += [
        Path(
            f"java/case-service/src/test/java/com/resolveflow/caseservice/casefile/{name}.java"
        )
        for name in (
            "ResumeAuthorizationMatrixApiTest",
            "InputMovesRetireApprovalApiTest",
            "ReviewQueueBackpressureTest",
        )
    ]
    summary = {
        "state": "COMPLETED",
        "scenario_runs": 80,
        **totals,
        "consume_wins_update_rejections": 10,
        "scope": "real Case HTTP/MySQL; explicit Commerce eligibility fixture; no MQ/fund settlement claim",
        "junit": tests,
        "files": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in files + [ROOT / path for path in sources]
        },
    }
    (REPORT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
