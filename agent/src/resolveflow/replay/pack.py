"""Immutable, hash-checked replay pack files. No production store is opened here."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ReplayMiss(RuntimeError):
    """A required recorded response, observation or file does not exist."""


class PackInvalid(RuntimeError):
    """A pack differs from its hash list or has an invalid shape."""


class UnsupportedRecord(RuntimeError):
    """The recorded trajectory is outside the selected strict subset."""


def _canonical(value: Any) -> bytes:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (content + "\n").encode()


def write_pack(directory: Path, document: dict[str, Any]) -> None:
    """Write once; never replace evidence from an earlier export."""
    directory.mkdir(parents=True, exist_ok=False)
    data = _canonical(document)
    (directory / "pack.json").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (directory / "files.json").write_bytes(_canonical({"schema_version": 1, "files": {"pack.json": digest}}))


def read_pack(directory: Path) -> dict[str, Any]:
    try:
        checksums = json.loads((directory / "files.json").read_bytes())
        data = (directory / "pack.json").read_bytes()
    except FileNotFoundError as missing:
        raise ReplayMiss(f"missing pack file: {missing.filename}") from missing
    except (OSError, json.JSONDecodeError) as error:
        raise PackInvalid("unreadable pack hash list") from error
    if checksums != {"schema_version": 1, "files": {"pack.json": hashlib.sha256(data).hexdigest()}}:
        raise PackInvalid("PACK_INVALID: file hash list differs")
    try:
        document = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackInvalid("PACK_INVALID: unreadable pack JSON") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise PackInvalid("PACK_INVALID: unsupported pack schema")
    required = {
        "evaluation_run_id", "source_run_id", "clock", "facts", "manifest", "budget",
        "model_calls", "tool_calls", "expected",
    }
    if not required <= document.keys():
        raise ReplayMiss(f"REPLAY_MISS: pack fields absent: {sorted(required - document.keys())}")
    if (not isinstance(document["model_calls"], list) or not isinstance(document["tool_calls"], list)
            or not isinstance(document["facts"], dict) or not isinstance(document["manifest"], dict)
            or not isinstance(document["budget"], dict) or not isinstance(document["expected"], dict)):
        raise PackInvalid("PACK_INVALID: pack field type")
    return document
