"""C06.2b/C06.2c: the tool server's defaults have to be the ports the services really use.

The defaults existed from the first version of ``tools/server.py``, and one of them was wrong: Commerce was
``8084`` when ``scripts/e2e_refund_chain.py:53`` declares ``COMMERCE_PORT = 8081``. Nothing failed, because the
only tests that ran the tools pointed them at a stub on an ephemeral port — the defaults were never exercised.
That is the shape this test exists to catch: a wrong default is not a loud failure, it is **every read against a
closed port**, which the tool layer honestly reports as ``UPSTREAM_UNAVAILABLE`` and ``retryable``. The tools
would say "the shop is down" and be believed.

The e2e script is the authority rather than a second copy of the numbers: it is what actually starts the two Java
processes and health-checks them, so if a port moves, it moves there first and this test goes red.
"""

from __future__ import annotations

import pathlib
import re

from resolveflow.tools import server

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
E2E = REPO_ROOT / "scripts" / "e2e_refund_chain.py"


def declared_port(name: str) -> str:
    """The port the e2e script declares for a service, read rather than restated."""
    match = re.search(rf"^{name}_PORT = (\d+)$", E2E.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None, f"the e2e script no longer declares {name}_PORT; this test's authority is gone"
    return match.group(1)


def test_tool_defaults_match_the_declared_ports() -> None:
    assert server.DEFAULT_CASE_BASE_URL == f"http://127.0.0.1:{declared_port('CASE')}"
    assert server.DEFAULT_COMMERCE_BASE_URL == f"http://127.0.0.1:{declared_port('COMMERCE')}"


def test_the_two_defaults_are_not_the_same_service() -> None:
    """A one-character copy-paste would point both tools at one service, and the reads would 404 confusingly."""
    assert server.DEFAULT_CASE_BASE_URL != server.DEFAULT_COMMERCE_BASE_URL


def test_both_defaults_are_loopback() -> None:
    """These are demonstration defaults: a default that reached off-host would be a deployment decision made here.

    ``docs/agent-spec.md:36``'s ``source_ref`` pattern forbids a URL precisely so a citation cannot point
    somewhere else; the same instinct applies to where the tools read by default.
    """
    for url in (server.DEFAULT_CASE_BASE_URL, server.DEFAULT_COMMERCE_BASE_URL):
        assert url.startswith("http://127.0.0.1:"), url