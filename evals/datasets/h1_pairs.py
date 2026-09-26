"""Validate and export isolated H1 synthetic inputs; Gold is never part of an export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INPUT = HERE / "h1-pairs-input.json"
GOLD = HERE / "h1-pairs-gold.json"
GOLD_ONLY = frozenset({"gold", "allowed_terminal_actions", "forbidden_terminal_actions", "must_observe",
                       "must_cite", "requires_question", "requires_human", "review_status"})
ACTIONS = frozenset({"REFUND", "REQUEST_INFO", "MANUAL_REVIEW", "REJECT"})


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    return value


def validate(inputs: dict[str, Any], gold: dict[str, Any]) -> None:
    if inputs.get("version") != gold.get("version") or inputs.get("origin") != "synthetic":
        raise ValueError("dataset version/origin mismatch")
    if inputs.get("split") != "test" or inputs.get("policy_version") != "H1-SYNTHETIC-v1":
        raise ValueError("H1 evaluation split or synthetic policy changed")
    cases = inputs.get("cases")
    rows = gold.get("gold")
    if not isinstance(cases, list) or not isinstance(rows, list) or len(cases) != 12 or len(rows) != 12:
        raise ValueError("H1 needs exactly six complete pairs and twelve Gold rows")
    by_pair: dict[str, dict[str, dict[str, Any]]] = {}
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or any(key in json.dumps(case) for key in GOLD_ONLY):
            raise ValueError("input contains Gold-only data")
        case_id = case.get("id")
        pair = case.get("pair")
        if not isinstance(case_id, str) or not isinstance(pair, str) or case_id not in (f"{pair}-A", f"{pair}-B"):
            raise ValueError("invalid case/pair id")
        if case_id in case_ids:
            raise ValueError("duplicate case id")
        case_ids.add(case_id)
        by_pair.setdefault(pair, {})[case_id[-1]] = case
    if set(by_pair) != {f"H1-{index:02d}" for index in range(1, 7)}:
        raise ValueError("six named H1 pairs required")
    for pair, sides in by_pair.items():
        if set(sides) != {"A", "B"}:
            raise ValueError(f"{pair}: incomplete pair")
        a, b = sides["A"], sides["B"]
        if a.get("description") != b.get("description") or a.get("scope") != b.get("scope"):
            raise ValueError(f"{pair}: complaint or authority scope differs")
        if not isinstance(a.get("facts"), dict) or not isinstance(b.get("facts"), dict) or a["facts"] == b["facts"]:
            raise ValueError(f"{pair}: authoritative facts do not differ")
    gold_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in case_ids or row["id"] in gold_ids:
            raise ValueError("Gold id missing, unknown or duplicated")
        gold_ids.add(row["id"])
        allowed = row.get("allowed_terminal_actions")
        forbidden = row.get("forbidden_terminal_actions")
        if not isinstance(allowed, list) or not allowed or not isinstance(forbidden, list):
            raise ValueError("Gold actions missing")
        if not set(allowed) <= ACTIONS or not set(forbidden) <= ACTIONS or set(allowed) & set(forbidden):
            raise ValueError("Gold actions invalid or contradictory")
        case = next(item for item in cases if item["id"] == row["id"])
        if not isinstance(row.get("must_observe"), list) or not set(row["must_observe"]) <= set(case["facts"]):
            raise ValueError("Gold required observation absent from synthetic facts")
        if (
            not isinstance(row.get("must_cite"), list)
            or not isinstance(row.get("requires_question"), bool)
            or not isinstance(row.get("requires_human"), bool)
        ):
            raise ValueError("Gold evidence/handling fields missing")
    if gold_ids != case_ids:
        raise ValueError("Gold does not cover all inputs")
    for pair, sides in by_pair.items():
        a_gold = next(row for row in rows if row["id"] == sides["A"]["id"])
        b_gold = next(row for row in rows if row["id"] == sides["B"]["id"])
        if "REFUND" not in a_gold["allowed_terminal_actions"] or "REFUND" not in b_gold["forbidden_terminal_actions"]:
            raise ValueError(f"{pair}: no divergent refund authority")


def export_case(inputs: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in inputs["cases"]:
        if case["id"] == case_id:
            return {"version": inputs["version"], "origin": inputs["origin"], "split": inputs["split"],
                    "policy_version": inputs["policy_version"], "case": case}
    raise ValueError(f"unknown case {case_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-case", metavar="H1-01-A", help="print one Gold-free case as JSON")
    args = parser.parse_args()
    inputs = _load(INPUT)
    validate(inputs, _load(GOLD))
    if args.export_case:
        print(json.dumps(export_case(inputs, args.export_case), ensure_ascii=False, sort_keys=True))
    else:
        print("H1 synthetic pairs: 6 pairs / 12 cases; Gold isolated; split=test; live runs=0")


if __name__ == "__main__":
    main()
