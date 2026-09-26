"""Explicit export and strict-only replay entry points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from resolveflow.replay.export import export_run
from resolveflow.replay.pack import PackInvalid, ReplayMiss, UnsupportedRecord
from resolveflow.replay.strict import ReplayMismatch, strict_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Selected synthetic ResolveFlow strict replay")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("directory", type=Path)
    export.add_argument("--synthetic-ack", action="store_true", help="attest that this run contains synthetic data")
    replay = sub.add_parser("strict")
    replay.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            if not args.synthetic_ack:
                parser.error("export requires --synthetic-ack")
            from resolveflow.runtime.db import Database

            database = Database()
            try:
                export_run(database, args.run_id, args.directory)
            finally:
                database.close()
            result = {"status": "EXPORTED", "source_run_id": args.run_id}
        else:
            result = strict_replay(args.directory)
    except (PackInvalid, ReplayMiss, ReplayMismatch, UnsupportedRecord) as error:
        print(json.dumps({"status": type(error).__name__, "detail": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
