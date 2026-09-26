from resolveflow.runtime.build_identity import source_identity


def test_unstamped_build_identity_tracks_source_and_lock(tmp_path) -> None:
    package = tmp_path / "resolveflow"
    package.mkdir()
    code = package / "sample.py"
    code.write_text("one", encoding="utf-8")
    lock = tmp_path / "uv.lock"
    lock.write_text("lock-one", encoding="utf-8")
    original = source_identity(package, lock)
    assert original == source_identity(package, lock)
    assert "unknown" not in original
    code.write_text("two", encoding="utf-8")
    assert original != source_identity(package, lock)
    changed = source_identity(package, lock)
    lock.write_text("lock-two", encoding="utf-8")
    assert changed != source_identity(package, lock)
