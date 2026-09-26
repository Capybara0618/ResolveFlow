from pathlib import Path

import pytest

from resolveflow.replay.pack import PackInvalid, ReplayMiss, read_pack, write_pack


def test_pack_hash_and_missing_record_fail_closed(tmp_path: Path) -> None:
    document = {"schema_version": 1, "evaluation_run_id": "evaluation", "source_run_id": "synthetic",
                "clock": "2026-09-26T00:00:00Z",
                "facts": {}, "manifest": {}, "budget": {}, "model_calls": [], "tool_calls": [], "expected": {}}
    path = tmp_path / "pack"
    write_pack(path, document)
    assert read_pack(path) == document
    (path / "pack.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PackInvalid):
        read_pack(path)
    (path / "pack.json").unlink()
    with pytest.raises(ReplayMiss):
        read_pack(path)


def test_pack_missing_field_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "missing-field"
    write_pack(path, {"schema_version": 1})
    with pytest.raises(ReplayMiss, match="pack fields absent"):
        read_pack(path)
