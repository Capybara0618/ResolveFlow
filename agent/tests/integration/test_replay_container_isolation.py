"""OS boundary: a real SQL write call from the replay image cannot reach agent_db."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from resolveflow.runtime.db import Database


def test_networkless_replay_container_cannot_write_business_database(agent_db: Database) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is unavailable")
    image = subprocess.run(  # noqa: S603 - fixed Docker CLI arguments
        [docker, "image", "inspect", "resolveflow-replay:local"], capture_output=True, text=True, check=False
    )
    if image.returncode:
        pytest.skip("build resolveflow-replay:local first")
    with agent_db.connection() as connection:
        connection.execute("CREATE TABLE replay_write_probe (value integer NOT NULL)")
    code = (
        "import psycopg, sys; from psycopg import sql; "
        "dsn='postgresql://agent:agent@host.docker.internal:55432/agent_db?connect_timeout=2'; "
        "conn=psycopg.connect(dsn); "
        "conn.execute(sql.SQL('INSERT INTO {}.replay_write_probe VALUES (1)').format(sql.Identifier(sys.argv[1]))); "
        "conn.commit()"
    )
    command = [docker, "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--user", "10001:10001",
               "--entrypoint", "/work/agent/.venv/bin/python", "resolveflow-replay:local", "-c", code,
               agent_db.schema]
    attempt = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)  # noqa: S603
    assert attempt.returncode != 0
    assert "OperationalError" in attempt.stderr
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) FROM replay_write_probe").fetchone()["count"]
    assert count == 0
