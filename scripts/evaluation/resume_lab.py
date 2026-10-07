"""Owned processes and dedicated schemas for local resume measurements."""

import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MYSQL = "resolveflow-review-demo-mysql-1"
JAVA = Path("C:/Users/hjn/.jdks/jdk-21.0.12.1+1/bin/java.exe")


def mysql(sql: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            MYSQL,
            "sh",
            "-c",
            'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -s --default-character-set=utf8mb4',
        ],
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def create_database(schema: str, account: str) -> None:
    assert re.fullmatch(r"resume_[a-z0-9_]+", schema)
    assert account in ("case_svc", "commerce")
    assert (
        mysql(
            f"SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='{schema}';"
        )
        == "0"
    ), schema
    mysql(
        f"CREATE DATABASE `{schema}`; GRANT ALL PRIVILEGES ON `{schema}`.* TO '{account}'@'%';"
    )


def start_java(
    service: str, schema: str, port: int, label: str, *, extra=(), env_extra=None
):
    import urllib.request

    assert service in ("case", "commerce")
    with __import__("socket").socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, f"port already owned: {port}"
    folder = ROOT / "tmp/resume/processes"
    folder.mkdir(parents=True, exist_ok=True)
    prefix = "CASE" if service == "case" else "COMMERCE"
    account = "case_svc" if service == "case" else "commerce"
    env = dict(
        os.environ,
        **{
            f"{prefix}_DB_URL": f"jdbc:mysql://127.0.0.1:3307/{schema}?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
            f"{prefix}_DB_USER": account,
            f"{prefix}_DB_PASSWORD": account,
            "SERVER_PORT": str(port),
            **(env_extra or {}),
        },
    )
    jar = ROOT / f"java/{service}-service/target/{service}-service-0.1.0-SNAPSHOT.jar"
    output = (folder / f"{label}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [str(JAVA), "-Xms256m", "-Xmx768m", "-jar", str(jar), *extra],
        cwd=ROOT,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output.close()
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() is None, f"{label} stopped; inspect local log"
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/actuator/health", timeout=2
                ) as response:
                    if b'"UP"' in response.read():
                        return process
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        raise TimeoutError(label)
    except BaseException:
        stop(process)
        raise


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
