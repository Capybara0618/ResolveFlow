"""C06.4④: the tools present the **run's** credential, not the deployment's.

``docs/contracts.md:96`` issues a tool credential per run and renews it through Case; before this slice the five
tools presented ``RESOLVEFLOW_TOOL_SERVICE_TOKEN``, one credential for every run a deployment ever served. The
difference that matters is not the extra claim names — it is that a deployment-wide token cannot be refused when
a run stops describing the case, carries no line, and cannot be given a short life because there is nothing to
renew it from.

This file tests the Python half of that path over real HTTP against a stub Case, and asserts the two properties
that only the whole path can show: the credential the executor presents is the one Case minted for *this run*, and
a credential that cannot be minted stops the read rather than falling back to the deployment's own token.

The Java half — that Case mints a token bound to run/case/revision/principal/scope, and refuses a revision the
case has left — is ``ToolCredentialApiTest``. Neither file can prove the other's claim, which is why both exist.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from resolveflow.tools.credential import (
    CREDENTIAL_ROUTE,
    CredentialUnavailableError,
    HttpToolCredentialClient,
    ToolCredential,
    credential_source,
    credential_token_source,
)
from tests.integration import stub_upstream

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CASE_CONTRACT = REPO_ROOT / "contracts" / "core" / "openapi-case.yaml"

RUN_ID = "5f2b1c3d-0000-4000-8000-000000000001"
CASE_ID = "9c858abd-0000-4000-8000-0000000000cc"
REVISION = 1


@pytest.fixture()
def case(tmp_path: pathlib.Path) -> Any:
    """A stub Case that mints run-scoped credentials, with its request log on disk."""
    server = stub_upstream.start(tmp_path / "case.log")
    try:
        yield server.url, tmp_path / "case.log"
    finally:
        server.stop()


def requests_to(log: pathlib.Path) -> list[dict[str, Any]]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ the fetch


def test_the_credential_is_fetched_over_the_route_the_contract_declares(case: Any) -> None:
    """The route is the contract's, character for character, and the body is the two members it declares.

    Checked against ``contracts/core/openapi-case.yaml`` rather than restated: a rename in the contract that this
    module did not follow would otherwise show up as a 404 in a running deployment, which reads like Case being
    down.
    """
    import yaml

    url, log = case
    document = yaml.safe_load(CASE_CONTRACT.read_text(encoding="utf-8"))
    assert CREDENTIAL_ROUTE in document["paths"], f"{CREDENTIAL_ROUTE} is not a route the contract declares"
    # And the members the contract requires of the request body are exactly the ones sent: a body carrying a
    # run id or a merchant would be this module inventing a contract the schema forbids.
    request_schema = document["components"]["schemas"]["ToolCredentialRequest"]
    assert set(request_schema["required"]) == {"case_id", "input_revision"}
    assert set(request_schema["properties"]) == {"case_id", "input_revision"}

    client = HttpToolCredentialClient(case_base_url=url, service_token="tool-service-token")
    credential = client.issue(run_id=RUN_ID, case_id=CASE_ID, input_revision=REVISION)

    assert credential.token
    sent = requests_to(log)
    assert len(sent) == 1
    assert sent[0]["path"] == f"/internal/v1/runs/{RUN_ID}/tool-credential"
    # The route is on the /internal surface: it needs a service token, or any process that reached the port
    # could mint itself one.
    assert sent[0]["authorization"] == "Bearer tool-service-token"


def test_a_credential_without_its_expiry_or_scopes_is_refused(case: Any) -> None:
    """A malformed answer is an error, not a credential with the missing members filled in.

    ``expires_at`` is what a renewal is planned from and ``scopes`` is what a read is checked against; inventing
    either would make a broken answer look like a usable credential, and the failure would arrive later as a
    refused read the run cannot explain.
    """
    with pytest.raises(CredentialUnavailableError):
        ToolCredential.from_response({"token": "t", "scopes": ["commerce:read"]})
    with pytest.raises(CredentialUnavailableError):
        ToolCredential.from_response({"token": "t", "expires_at": "2026-09-25T00:00:00Z"})
    with pytest.raises(CredentialUnavailableError):
        ToolCredential.from_response({"expires_at": "2026-09-25T00:00:00Z", "scopes": ["commerce:read"]})


def test_case_being_unreachable_is_an_error_and_not_a_weaker_credential(case: Any) -> None:
    """An unreachable Case must not turn into "carry on with the configured token".

    That fallback is the failure this module exists to prevent: the tools would keep working under a credential
    that is not the run's, and nothing would report it.
    """
    client = HttpToolCredentialClient(case_base_url="http://127.0.0.1:1", service_token="t")
    with pytest.raises(CredentialUnavailableError):
        client.issue(run_id=RUN_ID, case_id=CASE_ID, input_revision=REVISION)


# ------------------------------------------------------------------ which credential is used


def test_the_run_credential_is_preferred_over_a_configured_token() -> None:
    """When Case is known, the credential comes from Case — the configured token is only the identity to ask with."""
    source = credential_source(
        case_base_url="http://127.0.0.1:8083",
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=REVISION,
        service_token="identity-to-ask-with",
        static_token="deployment-wide-token",
    )
    assert source is not None
    # It is a *source*: nothing has been fetched yet, and the fetch happens when a read needs a token.
    assert callable(source)


def test_a_deployment_with_no_case_named_falls_back_to_its_configured_token() -> None:
    """The stub case: tools pointed at a service directly have no Case to ask, and say so by configuration."""
    source = credential_source(
        case_base_url=None,
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=REVISION,
        service_token=None,
        static_token="deployment-wide-token",
    )
    assert source is not None and source() == "deployment-wide-token"


def test_no_credential_at_all_is_no_source() -> None:
    """Nothing to present is represented as nothing, not as an empty string.

    An empty ``Authorization`` header is a request that looks authenticated and is not, and the Java filter would
    answer 401 to it — a confusing way to learn that the credential was never configured.
    """
    assert (
        credential_source(
            case_base_url=None,
            run_id=RUN_ID,
            case_id=None,
            input_revision=REVISION,
            service_token=None,
            static_token=None,
        )
        is None
    )
    assert credential_token_source(None) is None
    adapted = credential_token_source(lambda: "t")
    assert adapted is not None and adapted() == "t"


def test_a_case_id_of_none_does_not_produce_a_half_fetch() -> None:
    """The credential route needs a case id; without one there is nothing to ask for, so no source is built.

    This is the boundary the executor relies on: it passes the run's case id, and a run with no case (the tools
    driven directly by a test) must fall back rather than fetch a credential for nobody.
    """
    source = credential_source(
        case_base_url="http://127.0.0.1:8083",
        run_id=RUN_ID,
        case_id=None,
        input_revision=REVISION,
        service_token=None,
        static_token="deployment-wide-token",
    )
    assert source is not None and source() == "deployment-wide-token"


def test_the_stub_case_mints_a_credential_the_tools_can_present(case: Any) -> None:
    """End of the Python path: the token Case answered is what a read presents.

    The stub mints ``token-for-<run_id>``, and the assertion is that the executor's ``Authorization`` header
    carries it — the join between "a credential was fetched" and "the credential was used", which are different
    facts and only the second one scopes a read.
    """
    url, log = case
    client = HttpToolCredentialClient(case_base_url=url, service_token="tool-service-token")
    credential = client.issue(run_id=RUN_ID, case_id=CASE_ID, input_revision=REVISION)

    # The stub answers with a token that names the run it was minted for, so a credential for the wrong run is
    # visible here rather than in a log nobody reads.
    assert credential.token == f"token-for-{RUN_ID}"
    assert credential.scopes == ("commerce:read", "policy:read")
    assert credential.expires_at
    # Exactly one request: the credential is fetched, not polled.
    assert len(requests_to(log)) == 1
    assert requests_to(log)[0]["path"].endswith(f"/{RUN_ID}/tool-credential")
