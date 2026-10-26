"""Prove the frozen-cohort audit rejects corrupted money and execution evidence in memory."""

import copy
import json
import sys
from pathlib import Path

import audit as checker


def verify(raw):
    original_read = checker.read
    database = original_read(raw / "refund-formal-final-database.json")
    changes = [("duplicate provider request", "provider", "requests"),
               ("over refund", "operations", "refunded"),
               ("wrong authorization revision", "operations", "authorization_revision"),
               ("duplicate case closure", "operations", "closed_events")]
    results = []
    for label, group, key in changes:
        changed = copy.deepcopy(database)
        changed[group][0][key] += 1
        checker.read = lambda p, data=changed: data if p.name == "refund-formal-final-database.json" else original_read(p)
        try:
            checker.audit(raw)
        except AssertionError:
            results.append({"mutation": label, "rejected": True})
        else:
            raise AssertionError("audit accepted " + label)
        finally:
            checker.read = original_read
    return {"checks": results, "mutated_files": 0, "network_requests": 0}


if __name__ == "__main__":
    result = verify(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("xb") as output:
        output.write((json.dumps(result, indent=2) + "\n").encode())
    print("four in-memory corruptions rejected; original evidence unchanged")
