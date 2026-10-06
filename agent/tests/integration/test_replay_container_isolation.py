"""OS boundary: a real SQL write call from the replay image cannot reach agent_db."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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
    # The old fixed 55432 target could pass simply because that port was stopped.
    # Use the fixture's real database, and prove the identical write works with
    # networking before testing the OS boundary. Credentials travel through the
    # subprocess environment and are only used by this isolated-schema probe.
    options = conninfo_to_dict(agent_db.dsn)
    if options.get("host") in ("127.0.0.1", "localhost", "::1"):
        options["host"] = "host.docker.internal"
    options["connect_timeout"] = "2"
    environment = {**os.environ, "PROBE_DSN": make_conninfo(**options)}
    code = (
        "import os, psycopg, sys; from psycopg import sql; "
        "conn=psycopg.connect(os.environ['PROBE_DSN']); "
        "conn.execute(sql.SQL('INSERT INTO {}.replay_write_probe VALUES (1)').format(sql.Identifier(sys.argv[1]))); "
        "conn.commit()"
    )
    command = [
        docker,
        "run",
        "--rm",
        "--network",
        "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "--env",
        "PROBE_DSN",
        "--entrypoint",
        "/work/agent/.venv/bin/python",
        "resolveflow-replay:local",
        "-c",
        code,
        agent_db.schema,
    ]
    control = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30, env=environment)  # noqa: S603
    assert control.returncode == 0, "networked SQL write control failed; isolation is not established"
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM replay_write_probe").fetchone()["count"] == 1
        connection.execute("DELETE FROM replay_write_probe")
    command[command.index("bridge")] = "none"
    attempt = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30, env=environment)  # noqa: S603
    assert attempt.returncode != 0
    assert "OperationalError" in attempt.stderr
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) FROM replay_write_probe").fetchone()["count"]
    assert count == 0
