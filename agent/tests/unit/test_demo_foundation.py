"""Reset guards and fixed synthetic dataset, without touching a live database."""

import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import demo_foundation as foundation
import foundation_data
import reviewer_demo as demo


def test_baseline_counts_and_independent_store_accounts():
    data = foundation_data.catalog()
    assert (len(data["stores"]), len(data["products"]), len(data["skus"])) == (3, 30, 45)
    assert len({s["sku_id"] for s in data["skus"]}) == 45
    assert len({p["product_id"] for p in data["products"]}) == 30
    rows = foundation_data.accounts()
    assert len(rows) == len({a["username"] for a in rows}) == 20
    assert sum(a["role"] == "CUSTOMER" for a in rows) == 10
    for store in data["stores"]:
        owned = [a for a in rows if a["merchant_id"] == store["store_id"]]
        assert sorted(a["role"] for a in owned) == ["MERCHANT_ADMIN", "REVIEWER", "REVIEWER"]
        assert sum(p["store_id"] == store["store_id"] for p in data["products"]) == 10


def test_reset_without_explicit_flag_never_stops_or_clears():
    with patch.object(foundation, "checked_settings") as checked:
        with pytest.raises(demo.DemoRefused, match="explicit"):
            foundation.reset(authorized=False)
        checked.assert_not_called()


def test_reset_rejects_shared_ports_before_any_mutation():
    ports = dict(demo.DEFAULT_PORTS, mysql=3306)
    with patch.object(demo, "settings_from_environ", return_value=demo.Settings(ports=ports)):
        with patch.object(demo, "stop_owned") as stopped:
            with pytest.raises(demo.DemoRefused, match="fixed local demo"):
                foundation.checked_settings()
            stopped.assert_not_called()


def test_failed_backup_never_truncates_or_seeds():
    settings = demo.Settings()
    with (
        patch.object(foundation, "checked_settings", return_value=settings),
        patch.object(demo, "stop_owned"),
        patch.object(demo, "read_owned", return_value=[]),
        patch.object(demo, "tcp_open", return_value=False),
        patch.object(foundation, "backup", side_effect=demo.DemoRefused("backup failed")),
        patch.object(foundation, "truncate_business") as clear,
        patch.object(foundation, "seed") as seed,
    ):
        with pytest.raises(demo.DemoRefused, match="backup failed"):
            foundation.reset(authorized=True)
        clear.assert_not_called()
        seed.assert_not_called()


def test_paths_outside_demo_runtime_are_rejected():
    with pytest.raises(demo.DemoRefused, match="subtree"):
        foundation.local_path(demo.ROOT)


def test_large_sql_uses_stdin_instead_of_windows_command_line():
    statement = "SELECT '合成商品';\n" * 5000
    with (
        patch.object(demo, "live_container", return_value="fixed-demo-mysql"),
        patch.object(foundation.subprocess, "run", return_value=CompletedProcess([], 0)) as run,
    ):
        foundation.mysql_write(statement, demo.Settings())
        args, options = run.call_args
        assert statement not in " ".join(args[0])
        assert len(" ".join(args[0])) < 1024 and "-i" in args[0]
        assert options["input"] == statement.encode("utf-8")


def test_foundation_status_reads_current_counts_without_old_sample_manifest(tmp_path):
    (tmp_path / "foundation.json").write_text("{}", encoding="utf-8")
    log = Mock()
    with (
        patch.object(demo, "load_manifest") as old_manifest,
        patch.object(demo, "container_health", return_value="healthy"),
        patch.object(demo, "mysql_rows", return_value=[["3", "20", "30", "45", "0", "0"]]),
        patch.object(demo, "read_owned", return_value=[]),
    ):
        assert demo.command_status(demo.Settings(runtime_root=tmp_path), log) == 0
        old_manifest.assert_not_called()
        log.note.assert_any_call("live stores/accounts/products/skus/orders/cases=3/20/30/45/0/0")
