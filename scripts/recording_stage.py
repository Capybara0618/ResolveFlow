"""One additive filming stage. Original volumes are stopped and retained, never cleared.

Copies schema, catalog, exact policy index and selected identities only. Reviews are
prepared through normal APIs on three background purchases, not copied as orphan rows.
The active marker is used by the ordinary start/status/stop and logistics commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import reviewer_demo as runtime

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "tmp" / "recording-stage-v1"
ACTIVE = ROOT / "tmp" / "active-recording-stage.json"
COMPOSE = ROOT / "infra" / "compose.recording.yaml"
PROJECT = "resolveflow-recording-v1"
ENVIRONMENT = "recording-stage-v1"
DATASET = "reviewer-demo-recording-v1"
POLICY_TABLES = {"policy_index_child", "policy_index_chunk", "policy_index_generation"}
CASE_TABLES = (
    "flyway_schema_history",
    "identity_merchant",
    "platform_buyer",
    "identity_account",
    "buyer_customer_binding",
    "buyer_address",
    "policy_bundle",
    "policy_rule",
    "catalog_media",
)
COMMERCE_TABLES = (
    "flyway_schema_history",
    "catalog_store",
    "catalog_product",
    "catalog_sku",
    "catalog_store_presentation",
    "catalog_product_presentation",
)


def write_json(path: Path, value: dict) -> None:
    runtime.atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def activate(*, initializing: bool = False) -> runtime.Settings:
    if not ACTIVE.is_file() or json.loads(ACTIVE.read_text(encoding="utf-8")) != {
        "stage": ENVIRONMENT
    }:
        raise runtime.DemoRefused("拍摄环境选择记录不匹配")
    if not initializing and not (STAGE / "imported.json").is_file():
        raise runtime.DemoRefused(
            "拍摄环境尚未完成导入，保留现场，禁止普通启动写入半成品"
        )
    runtime.PROJECT, runtime.ENVIRONMENT = PROJECT, ENVIRONMENT
    runtime.COMPOSE_FILE, runtime.RUNTIME_ROOT = COMPOSE, STAGE
    runtime.MANIFEST_PATH = STAGE / "samples.json"
    os.environ["RESOLVEFLOW_USER_MEDIA_DIR"] = str(STAGE / "media")
    current = runtime.Settings(
        project=PROJECT,
        environment=ENVIRONMENT,
        dataset=DATASET,
        runtime_root=STAGE,
        manifest_path=runtime.MANIFEST_PATH,
    )
    runtime.guard(current)
    return current


def checked(
    command: list, *, content: bytes | None = None, path: Path | None = None
) -> bytes:
    result = subprocess.run(
        [str(a) for a in command],
        input=content,
        capture_output=True,
        timeout=240,
        check=False,
    )
    if result.returncode:
        raise runtime.DemoRefused(
            "拍摄资料命令失败："
            + result.stderr.decode("utf-8", errors="replace")[-400:]
        )
    if path:
        path.write_bytes(result.stdout)
    return result.stdout


def mysql_write(settings: runtime.Settings, sql: str) -> None:
    checked(
        [
            "docker",
            "exec",
            "-i",
            runtime.live_container("mysql", settings),
            "mysql",
            "-uroot",
            "-proot",
            "--default-character-set=utf8mb4",
        ],
        content=sql.encode("utf-8"),
    )


def fingerprint(settings: runtime.Settings) -> dict:
    """Data-only dump hashes after stopping owned applications; never a source write."""
    mysql = runtime.live_container("mysql", settings)
    pg = runtime.live_container("postgres", settings)
    out = {}
    for schema in ("case_db", "commerce_db"):
        value = checked(
            [
                "docker",
                "exec",
                mysql,
                "mysqldump",
                "-uroot",
                "-proot",
                "--no-tablespaces",
                "--set-gtid-purged=OFF",
                "--single-transaction",
                "--skip-comments",
                "--skip-dump-date",
                "--no-create-info",
                "--skip-triggers",
                "--hex-blob",
                "--order-by-primary",
                schema,
            ]
        )
        out[schema] = hashlib.sha256(value).hexdigest()
    value = checked(
        [
            "docker",
            "exec",
            pg,
            "pg_dump",
            "-U",
            "agent",
            "-d",
            "agent_db",
            "--data-only",
            "--no-owner",
        ]
    )
    # PostgreSQL emits a random \restrict key; it is not business data.
    value = b"\n".join(
        line
        for line in value.splitlines()
        if not line.startswith((b"\\restrict ", b"\\unrestrict "))
    )
    out["agent_db"] = hashlib.sha256(value).hexdigest()
    return out


def capture_source(source: runtime.Settings) -> None:
    folder = STAGE / "initial-source"
    folder.mkdir(parents=True, exist_ok=False)
    mysql = runtime.live_container("mysql", source)
    pg = runtime.live_container("postgres", source)
    buyer = runtime.mysql_rows(
        "SELECT buyer_id FROM case_db.identity_account WHERE username='demo_showcase' "
        "AND login_key='display01' AND enabled=TRUE",
        source,
    )
    if len(buyer) != 1:
        raise runtime.DemoRefused("未找到已确认的display01展示身份")
    buyer_id = buyer[0][0]
    if not all(c.isalnum() or c in "-_" for c in buyer_id):
        raise runtime.DemoRefused("展示身份格式异常")
    for schema, tables in (("case_db", CASE_TABLES), ("commerce_db", COMMERCE_TABLES)):
        common = [
            "docker",
            "exec",
            mysql,
            "mysqldump",
            "-uroot",
            "-proot",
            "--no-tablespaces",
            "--set-gtid-purged=OFF",
            "--single-transaction",
            "--skip-comments",
        ]
        checked(
            common + ["--no-data", "--routines", "--skip-add-drop-table", schema],
            path=folder / (schema + "-schema.sql"),
        )
        for table in tables:
            extra = []
            if table == "identity_account":
                extra = [
                    "--where=username IN ('demo_showcase','admin01','admin02','admin03','platform')"
                ]
            elif table in ("platform_buyer", "buyer_customer_binding"):
                extra = [f"--where=buyer_id='{buyer_id}'"]
            elif table == "buyer_address":
                extra = [
                    f"--where=buyer_id='{buyer_id}' AND deleted=FALSE AND is_default=TRUE"
                ]
            checked(
                common
                + [
                    "--no-create-info",
                    "--skip-triggers",
                    "--hex-blob",
                    "--complete-insert",
                    *extra,
                    schema,
                    table,
                ],
                path=folder / (schema + "-" + table + ".sql"),
            )
    pg_tables = (
        checked(
            [
                "docker",
                "exec",
                pg,
                "psql",
                "-U",
                "agent",
                "-d",
                "agent_db",
                "-tAc",
                "SELECT tablename FROM pg_tables WHERE schemaname='public'",
            ]
        )
        .decode()
        .split()
    )
    checked(
        [
            "docker",
            "exec",
            pg,
            "pg_dump",
            "-U",
            "agent",
            "-d",
            "agent_db",
            "-Fc",
            "--no-owner",
            *[
                f"--exclude-table-data=public.{t}"
                for t in pg_tables
                if t not in POLICY_TABLES
            ],
        ],
        path=folder / "policy-index.dump",
    )
    shutil.copyfile(source.runtime_root / "foundation.json", STAGE / "foundation.json")
    (STAGE / "media").mkdir()
    media_ids = runtime.mysql_rows(
        "SELECT avatar_id FROM case_db.identity_account WHERE username IN "
        "('demo_showcase','admin01','admin02','admin03','platform') AND avatar_id IS NOT NULL "
        "UNION SELECT media_id FROM case_db.catalog_media",
        source,
    )
    for (identity,) in media_ids:
        import uuid

        if str(uuid.UUID(identity)) != identity:
            raise runtime.DemoRefused("图片身份格式不匹配")
        shutil.copyfile(
            ROOT / "tmp" / "user-media" / (identity + ".png"),
            STAGE / "media" / (identity + ".png"),
        )
    write_json(STAGE / "source-witness.json", fingerprint(source))
    write_json(STAGE / "captured.json", {"buyer_id": buyer_id, "profile": ENVIRONMENT})


def import_stage(current: runtime.Settings) -> None:
    folder = STAGE / "initial-source"
    if (
        runtime.mysql_scalar(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='case_db'",
            current,
        )
        != "0"
    ):
        raise runtime.DemoRefused("拍摄库已存在表，拒绝覆盖；检查此前初始化记录")
    for schema, tables in (("case_db", CASE_TABLES), ("commerce_db", COMMERCE_TABLES)):
        payload = (
            b"USE "
            + schema.encode()
            + b";\n"
            + (folder / (schema + "-schema.sql")).read_bytes()
        )
        for table in tables:
            payload += b"\n" + (folder / (schema + "-" + table + ".sql")).read_bytes()
        checked(
            [
                "docker",
                "exec",
                "-i",
                runtime.live_container("mysql", current),
                "mysql",
                "-uroot",
                "-proot",
                "--default-character-set=utf8mb4",
            ],
            content=payload,
        )
    # A source-browser token must not remain valid after switching stages.
    mysql_write(
        current,
        "UPDATE case_db.identity_account SET identity_version=identity_version+1;",
    )
    checked(
        [
            "docker",
            "exec",
            "-i",
            runtime.live_container("postgres", current),
            "pg_restore",
            "-U",
            "agent",
            "-d",
            "agent_db",
            "--no-owner",
            "--exit-on-error",
        ],
        content=(folder / "policy-index.dump").read_bytes(),
    )
    write_json(STAGE / "imported.json", {"profile": ENVIRONMENT})


def prepare() -> None:
    if ACTIVE.exists():
        raise runtime.DemoRefused(
            "拍摄环境已选中；使用正常start/status，不重复生成初始订单"
        )
    if STAGE.exists():
        raise runtime.DemoRefused(
            "已有拍摄准备目录，保留现场；先检查初始化阶段，不自动重置"
        )
    source = runtime.settings_from_environ()
    if (
        source.project != "resolveflow-review-demo"
        or source.runtime_root != ROOT / "tmp" / "reviewer-demo"
    ):
        raise runtime.DemoRefused("来源必须是已确认的验收环境")
    runtime.guard(source)
    runtime.stop_owned(source)
    if runtime.read_owned(source) or any(
        runtime.tcp_open("127.0.0.1", source.ports[k])
        for k in ("case", "commerce", "agent", "gateway", "frontend")
    ):
        raise runtime.DemoRefused("应用尚未全部停止，不开始复制")
    capture_source(source)
    stopped = runtime.compose("stop", settings=source)
    if stopped.returncode:
        raise runtime.DemoRefused("原依赖未完整停止；原卷保留")
    write_json(ACTIVE, {"stage": ENVIRONMENT})
    current = activate(initializing=True)
    up = runtime.compose("up", "-d", settings=current)
    if up.returncode or not runtime.wait_for(
        "recording datastores",
        lambda: all(
            runtime.container_health(r, current) == "healthy"
            for r in ("mysql", "postgres", "redis")
        ),
        timeout=180,
    ):
        raise runtime.DemoRefused("拍摄依赖未就绪，原卷未改")
    import_stage(current)
    print(
        "拍摄基础已复制；原数据卷已保留。下一步启动并准备3笔评价背景订单。", flush=True
    )


def original_settings() -> runtime.Settings:
    runtime.PROJECT, runtime.ENVIRONMENT = (
        "resolveflow-review-demo",
        "reviewer-demo-2026-09",
    )
    runtime.COMPOSE_FILE = ROOT / "infra/compose.reviewer-demo.yaml"
    runtime.RUNTIME_ROOT = ROOT / "tmp/reviewer-demo"
    runtime.MANIFEST_PATH = ROOT / "reports/reviewer-demo/samples.json"
    os.environ.pop("RESOLVEFLOW_USER_MEDIA_DIR", None)
    return runtime.Settings()


def select_original() -> None:
    current = activate()
    log = runtime.Log(STAGE / "select-original.log", "保留拍摄数据，切回验收环境")
    if runtime.command_stop(current, log) or runtime.read_owned(current):
        raise runtime.DemoRefused("拍摄服务未全部停止，保持原选择")
    original_settings()
    ACTIVE.unlink()  # Only this exact selection file; neither data directory is removed.
    print("已选择原验收环境；两套数据卷均保留。运行start.ps1即可启动原环境。")


def verify_original() -> None:
    """Read-only source verification, with both application sets stopped during the swap."""
    current = activate()
    log = runtime.Log(STAGE / "verify-original.log", "核对原数据完整性")
    if runtime.command_stop(current, log) or runtime.read_owned(current):
        raise runtime.DemoRefused("拍摄应用未完整停止，暂不切换依赖")
    source = original_settings()
    try:
        up = runtime.compose("up", "-d", "mysql", "postgres", settings=source)
        if up.returncode or not runtime.wait_for(
            "source databases",
            lambda: all(
                runtime.container_health(r, source) == "healthy"
                for r in ("mysql", "postgres")
            ),
            timeout=180,
        ):
            raise runtime.DemoRefused("原数据库未就绪，不能完成只读核对")
        expected = json.loads(
            (STAGE / "source-witness.json").read_text(encoding="utf-8")
        )
        observed = fingerprint(source)
        result = {
            "source_data_unchanged": observed == expected,
            "schemas": list(expected),
        }
        write_json(STAGE / "source-integrity.json", result)
        if observed != expected:
            raise runtime.DemoRefused("原数据库摘要不一致，保留所有现场待核对")
        print("原Case/Commerce/Agent完整数据摘要与准备前一致。", flush=True)
    finally:
        runtime.compose("stop", settings=source)
        selected = activate()
        up = runtime.compose("up", "-d", settings=selected)
        if up.returncode:
            raise runtime.DemoRefused("拍摄依赖恢复失败，请检查，数据卷均保留")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["prepare", "verify-original", "select-original", "select-recording"],
    )
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "verify-original":
        verify_original()
    elif args.command == "select-original":
        select_original()
    else:
        if ACTIVE.exists() or not (STAGE / "imported.json").is_file():
            raise runtime.DemoRefused("拍摄环境已选中或尚未完成导入")
        source = original_settings()
        if runtime.command_stop(source, runtime.Log()) or runtime.read_owned(source):
            raise runtime.DemoRefused("原应用未完整停止，暂不切换")
        write_json(ACTIVE, {"stage": ENVIRONMENT})
        print("已选择现有拍摄数据；运行start.ps1即可继续，不重置已拍订单。")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
