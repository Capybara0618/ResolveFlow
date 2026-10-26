"""Freeze and audit D2 authorization actions on the existing isolated Case/MySQL tests."""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.backend_lab import ROOT, child_env, run, sha256
from evaluation.trade_request_journal import durable

TEST = "java/case-service/src/test/java/com/resolveflow/caseservice/casefile/ResumeAuthorizationMatrixApiTest.java"
JUNIT = "java/case-service/target/surefire-reports/TEST-com.resolveflow.caseservice.casefile.ResumeAuthorizationMatrixApiTest.xml"


def scenario_manifest():
    return {
        "V1": {"change": "append statement", "rejected_actions": ["APPROVE"], "old_attempts": 1},
        "V2": {"change": "verify CONFIRMED/REFUTED alternately", "rejected_actions": ["APPROVE"], "old_attempts": 1},
        "V3": {"change": "approved then new statement", "rejected_actions": ["CONSUME"], "old_attempts": 1},
        "V4": {"change": "statement commits before approval in ordered threads", "rejected_actions": ["APPROVE"], "old_attempts": 1},
        "V5": {"change": "statement commits before consumption in ordered threads", "rejected_actions": ["CONSUME"], "old_attempts": 1},
        "V6": {"change": "cancel commits before consumption", "rejected_actions": ["CONSUME"], "old_attempts": 1},
        "V7": {"change": "new input then old callback/approval", "rejected_actions": ["APPROVE"], "old_attempts": 1, "callback": "STALE"},
        "V8": {"change": "two consecutive revision changes", "rejected_actions": ["APPROVE", "APPROVE"], "old_attempts": 2},
        "consume-wins": {"change": "consume commits before update/cancel", "rejected_actions": ["UPDATE_INPUT", "CANCEL"]},
    }


def inspect_record(row):
    if row["scenario"] == "consume-wins":
        assert row["update_rejected"] and row["cancel_rejected"]
        assert row["revision_before"] == row["revision_after"]
        assert row["command_count"] == row["outbox_count"] == 1
        return Counter(consume_first=1, update_rejections=1, cancel_rejections=1, valid_consumptions=1)
    spec = scenario_manifest()[row["scenario"]]
    assert row["old_authorization_status"] == "REVOKED"
    assert row["old_command_count"] == row["old_outbox_count"] == 0
    assert row["control_command_count"] == row["control_outbox_count"] == 1 and row["control_status"] == "CONSUMED"
    assert row["final_revision"] >= row["old_revision"] if row["scenario"] == "V6" else row["final_revision"] > row["old_revision"]
    assert [a["action"] for a in row["attempt_records"]] == spec["rejected_actions"]
    counts = Counter(valid_consumptions=1)
    for attempt in row["attempt_records"]:
        if attempt["action"] == "CONSUME":
            assert not attempt["dispatched"] and attempt["reason"]
            counts["consume_rejections"] += 1
        else:
            assert attempt["http_status"] == 409
            counts["approval_rejections"] += 1
    if row["scenario"] == "V7":
        assert row["callback_disposition"] == "STALE"
        counts["stale_callbacks"] += 1
    return counts


def freeze(folder):
    folder.mkdir(parents=True, exist_ok=False)
    sources = run(["git", "ls-files", "java/case-service/src", "java/shared-kernel/src", "java/pom.xml",
                   "java/case-service/pom.xml", "java/shared-kernel/pom.xml"]).splitlines()
    sources += [str(Path(__file__).relative_to(ROOT)).replace("\\", "/")]
    durable(folder / "manifest.json", {"git_sha": run(["git", "rev-parse", "HEAD"]), "scenarios": scenario_manifest(),
            "expected_matrix_rows": 90, "scope": "Case HTTP / production consumption transaction / new Testcontainers MySQL; Commerce eligibility stub",
            "sources": {name: sha256(ROOT / name) for name in sources}, "test": TEST,
            "model_requests": 0, "business_databases_touched": False})


def verify(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name, value in manifest["sources"].items():
        assert sha256(ROOT / name) == value, "frozen source changed: " + name
    return manifest


def execute(folder):
    verify(folder)
    durable(folder / "execution-started.json", {"manifest_sha256": sha256(folder / "manifest.json")})
    env = child_env()
    env["JAVA_HOME"] = str(Path.home() / ".jdks/jdk-21.0.12.1+1")
    command = [str(ROOT / "java/mvnw.cmd"), "-B", "-pl", "case-service", "-am",
               "-Dtest=ResumeAuthorizationMatrixApiTest", "-Dsurefire.failIfNoSpecifiedTests=false",
               "-Dresolveflow.resume.authorization.report-dir=" + (folder / "rounds").relative_to(ROOT).as_posix(), "test"]
    log = ROOT / "tmp" / (folder.name + "-maven.log")
    with log.open("xb") as output:
        result = subprocess.run(command, cwd=ROOT / "java", env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
    durable(folder / "execution-exit.json", {"exit_code": result.returncode, "command": command,
                                           "log_sha256": sha256(log), "java_home": env["JAVA_HOME"]})
    if result.returncode:
        raise RuntimeError("Maven failed; retained original rows/log, no rerun: " + str(log))


def analyze(folder):
    manifest = verify(folder)
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "rounds").glob("*.json"))]
    assert len(rows) == manifest["expected_matrix_rows"]
    counts, scenarios = Counter(), Counter()
    for row in rows:
        counts.update(inspect_record(row))
        scenarios[row["scenario"]] += 1
    assert scenarios == {key: 10 for key in scenario_manifest()}
    assert len({(row["scenario"], row["trial"]) for row in rows}) == 90
    root = ElementTree.parse(ROOT / JUNIT).getroot()
    assert all(root.attrib[key] == "0" for key in ("failures", "errors", "skipped"))
    cases = [case.attrib for case in root.findall("testcase")]
    measured = [c for c in cases if c["name"].startswith(("expiredRevisionAndValidControl", "consumedInputsCannotBeUpdated"))]
    assert len(measured) == 90
    durable(folder / "junit-sanitized.json", {"suite": root.attrib, "testcases": cases, "xml_sha256": sha256(ROOT / JUNIT),
                                            "matrix_tests": len(measured), "inherited_tests": len(cases) - len(measured)})
    durable(folder / "summary.json", {"matrix_rows": len(rows), "scenarios": dict(scenarios), "observed": dict(counts),
            "old_authorization_attempts": counts["approval_rejections"] + counts["consume_rejections"],
            "no_commands_for_revoked_authorizations": True, "illegal_consumptions": 0,
            "junit_total": len(cases), "files": {str(p.relative_to(folder)): sha256(p) for p in folder.rglob("*.json")},
            "scope": manifest["scope"], "model_requests": 0})
    print(json.dumps(dict(counts)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "execute", "analyze"))
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.experiment_id):
        raise ValueError("invalid experiment identifier")
    folder = ROOT / "reports/backend-resume-v1" / args.experiment_id
    {"freeze": freeze, "execute": execute, "analyze": analyze}[args.action](folder)


if __name__ == "__main__":
    main()
