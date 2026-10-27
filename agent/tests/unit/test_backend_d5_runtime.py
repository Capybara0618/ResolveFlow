import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_d5_runtime import free_ports, unpack


def test_unpacked_application_bytes_and_only_boot_content(tmp_path):
    source = tmp_path / "app.jar"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("BOOT-INF/classes/com/example/App.class", b"unchanged-app")
        archive.writestr("BOOT-INF/lib/dependency.jar", b"unchanged-library")
        archive.writestr("META-INF/MANIFEST.MF", b"not-application")
    result = unpack(source, tmp_path / "unpacked")
    assert set(result) == {"classes/com/example/App.class", "lib/dependency.jar"}
    assert (tmp_path / "unpacked/classes/com/example/App.class").read_bytes() == b"unchanged-app"
    with pytest.raises(FileExistsError):
        unpack(source, tmp_path / "unpacked")


def test_unpack_rejects_traversal(tmp_path):
    source = tmp_path / "bad.jar"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("BOOT-INF/classes/../../escape", b"invalid")
    with pytest.raises(ValueError, match="unsafe"):
        unpack(source, tmp_path / "new")
    assert not (tmp_path / "escape").exists()


def test_reserved_probe_ports_are_distinct_and_exclude_existing_ports():
    values = free_ports(8, {3306, 6379, 8080})
    assert len(set(values)) == 8 and not set(values) & {3306, 6379, 8080}


def test_seed_literals_and_constant_identifier_guard():
    from evaluation.backend_d5_seed import insert, literal

    assert literal(None) == "NULL"
    assert literal("customer's") == "'customer''s'"
    assert list(insert("case_db.example", ("id", "amount"), [("one", 42)])) == [
        "INSERT INTO case_db.example(id,amount) VALUES ('one',42);"
    ]
    with pytest.raises(ValueError):
        list(insert("case_db.bad;drop", ("id",), [("one",)]))
