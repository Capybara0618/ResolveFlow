"""Compatibility entry for the current isolated retrieval dataset (60 queries).

Old 40-query scores are retired. --report remains accepted for verify callers.
--skip-dense explicitly runs BM25 only; no dense result is fabricated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.agent_eval import main as evaluate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--skip-dense", action="store_true")
    args = parser.parse_args()
    arguments = ["rag"]
    if args.report:
        arguments += ["--output", str(args.report)]
    if args.skip_dense:
        arguments += ["--bm25-only"]
    return evaluate(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
