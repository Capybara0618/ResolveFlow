"""ResolveFlow local application lifecycle. Normal startup always enables real investigation.

Reuse the existing process/port/container guards and resource identities to preserve data.
Scenario drivers, synthetic transactions and reset are never part of this entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser

import reviewer_demo as runtime


class ProjectLog(runtime.Log):
    """Use application terminology while retaining the underlying diagnostic record."""

    @staticmethod
    def label(text: str) -> str:
        return (
            text.replace("prepared demo backend", "ResolveFlow backend")
            .replace("the demo ", "the local ")
            .replace("demo ", "")
        )

    def note(self, text: str) -> None:
        # Scenario explanations belong to the separate acceptance tooling.
        if "the Agent is started per scenario" not in text:
            super().note(self.label(text))

    def step(self, text: str, ok: bool = True, detail: str = "") -> None:
        super().step(self.label(text), ok, self.label(detail))

    def section(self, text: str) -> None:
        super().section(self.label(text))


def settings() -> runtime.Settings:
    current = runtime.settings_from_environ()
    if (
        current.project != runtime.PROJECT
        or current.ports != runtime.DEFAULT_PORTS
        or current.runtime_root.resolve() != runtime.RUNTIME_ROOT.resolve()
    ):
        raise runtime.DemoRefused(
            "正式启动入口只使用当前本机项目配置，拒绝覆盖共享环境"
        )
    runtime.guard(current)
    return current


def require_application_data(current: runtime.Settings) -> None:
    marker = current.runtime_root / "foundation.json"
    if not marker.is_file():
        raise runtime.DemoRefused(
            "缺少基础数据初始化记录，请按 docs/local-runtime.md 完成首次配置；启动不会自动清库"
        )
    data = json.loads(marker.read_text(encoding="utf-8"))
    if (
        data.get("profile") != "foundation-v1"
        or data.get("role_profile") != "merchant-single-v1"
    ):
        raise runtime.DemoRefused(
            "当前账号数据未升级到三角色，请先完成数据升级；启动不会替换已有记录"
        )


def policies_ready(current: runtime.Settings) -> bool:
    marker = json.loads(
        (current.runtime_root / "foundation.json").read_text(encoding="utf-8")
    )
    bundles = marker.get("bundles", [])
    if not bundles or not all(
        isinstance(b, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", b) for b in bundles
    ):
        return False
    identities = ",".join("'" + b + "'" for b in bundles)
    rows = runtime.mysql_rows(
        f"SELECT bundle_id,manifest_hash FROM case_db.policy_bundle WHERE bundle_id IN ({identities})",
        current,
    )
    if len(rows) != len(set(bundles)):
        return False
    for bundle, digest in rows:
        if bundle not in bundles or not re.fullmatch(r"[a-f0-9]{64}", digest):
            return False
        if (
            runtime.postgres_scalar(
                f"SELECT COUNT(*) FROM policy_index_generation WHERE bundle_id='{bundle}' AND manifest_hash='{digest}' AND status='READY'",
                current,
            )
            != "1"
        ):
            return False
    return True


def start(
    current: runtime.Settings, log: ProjectLog, *, build: bool, open_browser: bool
) -> int:
    # Fail before starting or replacing any process. Never fall back to read-only/mock.
    if not os.environ.get("RESOLVEFLOW_MODEL_API_KEY", "").strip():
        raise runtime.DemoRefused("缺少 Deepseek_API_KEY，无法启动完整调查服务")
    require_application_data(current)
    log.section("启动 ResolveFlow")
    if runtime.stage_ready(current) and runtime.tcp_open(
        "127.0.0.1", current.ports["broker"]
    ):
        log.step(
            "前后端依赖与 Java 服务已运行，复用现有进程", True, current.gateway_url
        )
    else:
        runtime.command_prepare(current, log, build=build, preserve_ready_index=True)
    if not policies_ready(current):
        raise runtime.DemoRefused(
            "基础政策与精确版本索引尚未就绪，不能将启动报告为完成"
        )
    runtime.start_readonly_agent(current, log, live=True, architecture="staged-v1")
    runtime.start_frontend(current, log)
    if not runtime.owns_port(
        current, "agent-live", current.ports["agent"]
    ) or not runtime.agent_health(current, architecture="staged-v1"):
        raise runtime.DemoRefused("真实调查服务尚未就绪，不能将启动报告为完成")
    if status(current, log) != 0:
        raise runtime.DemoRefused("仍有组件未就绪，请按失败项排查后重新启动")
    url = current.frontend_url + "/#/shop"
    log.step("前后端、真实 Agent 调查与政策检索已启动", True)
    log.note(f"浏览器地址：{url}")
    if open_browser and not webbrowser.open(url, new=2):
        log.note("默认浏览器未打开，请手动访问上面的地址")
    return 0


def status(current: runtime.Settings, log: ProjectLog) -> int:
    log.section("ResolveFlow 服务状态")
    checks = [
        ("MySQL", runtime.container_health("mysql", current) == "healthy"),
        ("PostgreSQL", runtime.container_health("postgres", current) == "healthy"),
        ("Redis", runtime.container_health("redis", current) == "healthy"),
        (
            "消息服务",
            runtime.tcp_open("127.0.0.1", current.ports["namesrv"])
            and runtime.tcp_open("127.0.0.1", current.ports["broker"]),
        ),
        (
            "Gateway",
            runtime.healthy_and_owned(
                current, "gateway", current.ports["gateway"], current.gateway_url
            ),
        ),
        (
            "Case",
            runtime.healthy_and_owned(
                current, "case-service", current.ports["case"], current.case_url
            ),
        ),
        (
            "Commerce",
            runtime.healthy_and_owned(
                current,
                "commerce-service",
                current.ports["commerce"],
                current.commerce_url,
            ),
        ),
        (
            "Agent（真实调查配置）",
            runtime.owns_port(current, "agent-live", current.ports["agent"])
            and runtime.agent_health(current, architecture="staged-v1"),
        ),
        (
            "网页",
            runtime.owns_port(current, "frontend", current.ports["frontend"])
            and runtime.frontend_health(current),
        ),
    ]
    # Stopped databases should produce a complete status report, not a SQL error.
    checks.append(
        (
            "基础政策精确版本索引",
            checks[0][1] and checks[1][1] and policies_ready(current),
        )
    )
    for name, ready in checks:
        log.step(name, ready)
    log.note("status 检查本机进程与健康接口，不发起模型请求")
    return 0 if all(ready for _, ready in checks) else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="ResolveFlow 本机项目运行管理")
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command != "start" and (args.skip_build or args.no_browser):
        parser.error("构建与浏览器选项仅用于 start")
    log = None
    try:
        current = settings()
        log = ProjectLog(
            runtime.log_path(current, "project-" + args.command),
            "ResolveFlow " + args.command,
        )
        if args.command == "start":
            result = start(
                current,
                log,
                build=not args.skip_build,
                open_browser=not args.no_browser,
            )
        elif args.command == "stop":
            result = runtime.command_stop(current, log)
            if log.failures:
                result = 1
                log.note("停止未全部完成，请查看失败项")
            else:
                log.note(
                    "应用与所属依赖容器已停止，数据卷保留，下一次启动继续使用原数据"
                )
        else:
            result = status(current, log)
        log.flush("PASSED" if result == 0 else "FAILED")
        return result
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        message = str(error)
        secret = os.environ.get("RESOLVEFLOW_MODEL_API_KEY", "")
        if secret:
            message = message.replace(secret, "[redacted]")
        if log is not None:
            log.step(message, False)
            log.flush("FAILED")
        else:
            print("ResolveFlow 启动失败：" + message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
