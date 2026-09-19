"""C00.3: the startable set is one list, and it is the core profile's.

C00.3 asks the startup and smoke selection to stop requiring fulfillment, Nacos and the
full observability stack (docs/core-scope.md:32, docs/architecture.md:43), while keeping
the old protocol's assets reachable and keeping every failure assertion
(docs/engineering.md:40). Two temptations break that quietly:

* a second service list inside ``scripts/verify.ps1``, which drifts from
  ``contracts/core/profile.json`` the first time one side is edited;
* bringing a container back into the default ``docker compose up`` set because a
  developer needed it once, which makes the "core does not require it" claim false
  without anyone editing a document.

Both are checked here by reading the two artefacts the run actually uses.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from resolveflow.contracts._schemaio import REPO_ROOT
from resolveflow.contracts.core_profile import CoreProfile, load_core_profile

VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify.ps1"
COMPOSE_FILE = REPO_ROOT / "infra" / "compose.yaml"

#: Containers that must never be part of the default (profile-less) compose set.
NOT_DEFAULT_CONTAINERS = ("nacos", "sentinel", "otel-collector", "prometheus", "grafana", "tempo", "jaeger")


@pytest.fixture()
def profile() -> CoreProfile:
    return load_core_profile()


@pytest.fixture()
def script_text() -> str:
    return VERIFY_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture()
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def launcher_entries(script: str) -> dict[str, dict[str, str]]:
    """The ``@{ Name = 'x'; Jar = '...'; Port = n }`` rows the smoke loop starts from."""
    pattern = re.compile(
        r"@\{\s*Name\s*=\s*'(?P<name>[^']+)';\s*Jar\s*=\s*'(?P<jar>[^']+)';\s*Port\s*=\s*(?P<port>\d+)\s*\}"
    )
    return {
        match.group("name"): {"jar": match.group("jar"), "port": match.group("port")}
        for match in pattern.finditer(script)
    }


# ------------------------------------------------------------------ services


def test_every_profile_service_has_a_launcher(profile: CoreProfile, script_text: str) -> None:
    """A service in the profile with no launcher would be skipped, not reported."""
    startable = {name for name in profile.core_service_names if profile.language_of(name) == "java"}
    startable |= set(profile.compat_only_services)
    assert set(launcher_entries(script_text)) == startable


def test_the_default_profile_is_core_and_compat_stays_reachable(script_text: str) -> None:
    assert re.search(r"\$Profile\s*=\s*'core'", script_text), "the default smoke profile must be core"
    assert re.search(r"ValidateSet\('core',\s*'compat'\)", script_text), "compat must stay selectable"


def test_the_smoke_selection_reads_the_profile(script_text: str) -> None:
    """The started set is the profile's, not a second list inside the script."""
    assert "contracts/core/profile.json" in script_text
    assert "compat_only_services" in script_text
    assert "core_services" in script_text
    assert re.search(r"\$Profile\s*-eq\s*'compat'", script_text)


def test_the_agent_is_started_by_the_smoke_suite(script_text: str) -> None:
    """The Agent is Python, so its launcher is not one of the jar rows; it must still exist."""
    assert "smoke-agent-service" in script_text
    assert "uvicorn resolveflow.api.app:app" in script_text


# ------------------------------------------------------------------ containers


def test_nacos_is_behind_the_compat_compose_profile(compose: dict[str, Any]) -> None:
    assert compose["services"]["nacos"]["profiles"] == ["compat"]


def test_core_containers_have_no_profile_so_they_start_by_default(compose: dict[str, Any]) -> None:
    """The datastores and RocketMQ are core infrastructure (profile.json deployment.infrastructure)."""
    for name in ("mysql", "postgres", "redis", "rocketmq-namesrv", "rocketmq-broker"):
        assert name in compose["services"], name
        assert "profiles" not in compose["services"][name], f"{name} must start with the default set"


@pytest.mark.parametrize("container", NOT_DEFAULT_CONTAINERS)
def test_not_required_containers_never_start_by_default(compose: dict[str, Any], container: str) -> None:
    service = compose["services"].get(container)
    if service is None:
        return
    assert "profiles" in service, f"{container} is not required by the core profile and must be behind a profile"


def test_the_profile_and_compose_agree_on_what_is_not_required(profile: CoreProfile, compose: dict[str, Any]) -> None:
    """Anything the profile calls not-required must be absent or behind a profile."""
    for name in profile.not_required:
        service = compose["services"].get(name)
        if service is not None:
            assert "profiles" in service, f"{name} is listed as not_required but starts by default"


# ------------------------------------------------------------------ the script itself


def test_the_suite_list_is_profiled_but_not_weakened(script_text: str) -> None:
    """C00.3 keeps the old entry point and the failure assertions (docs/engineering.md:40)."""
    assert "'smoke'" in script_text
    assert "SUITE '$Suite' FAILED" in script_text
    assert "Refusing to report success for a suite that ran nothing" in script_text


def test_the_report_records_which_profile_ran(script_text: str) -> None:
    """A passing smoke report has to say what it started, or it cannot be read later."""
    assert re.search(r'Write-Both "  profile : \$Profile"', script_text)


def test_no_source_file_is_removed_for_the_core_profile() -> None:
    """Deferred capabilities stay in the tree as compatibility assets (docs/core-scope.md:17)."""
    assert (REPO_ROOT / "java" / "fulfillment-service").is_dir()
    assert (REPO_ROOT / "contracts" / "openapi-fulfillment.yaml").is_file()
    assert Path(REPO_ROOT / "java" / "fulfillment-service" / "src" / "test").is_dir()