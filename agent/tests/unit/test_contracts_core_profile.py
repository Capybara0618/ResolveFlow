"""C00.1: the core-v1.2 profile is the machine-readable allowlist for the core scope.

docs/core-scope.md decides what the core version must deliver and docs/core-contracts.md
decides which wire versions belong to it. The T02 baselines stay on disk as compat
assets, so this profile has to state - and these tests have to prove - that a capability
which only exists in the old protocol (RESHIP, entitlement commit/release, cancel before
start) is *not* granted by the core profile. A profile that merely repeated the old
schemas would make the migration look done while the core protocol stayed permissive.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from resolveflow.contracts import enums
from resolveflow.contracts._schemaio import REPO_ROOT, SCHEMA_FILES
from resolveflow.contracts.core_profile import CoreProfile, CoreProfileError, load_core_profile

PROFILE_PATH = "contracts/core/profile.json"

#: The old T02 documents. C00 adds a core protocol beside them; it must not consume them.
COMPAT_OPENAPI = (
    "contracts/openapi-case.yaml",
    "contracts/openapi-commerce.yaml",
    "contracts/openapi-agent.yaml",
    "contracts/openapi-fulfillment.yaml",
)

#: The capability ids docs/core-scope.md section 2 defers. Every one of them is something
#: the old protocol already models, which is exactly why the core profile must name them.
DEFERRED = (
    "reship",
    "inventory",
    "entitlement_saga",
    "execution_cancel",
    "partial_refund",
    "counterfactual_replay",
    "world_replayer",
    "full_rag_ablation",
    "observability_cluster",
    "multi_agent",
)


@pytest.fixture(scope="module")
def profile() -> CoreProfile:
    return load_core_profile()


def _authority_hash_fields() -> set[str]:
    """Read the payload_hash field list out of docs/core-contracts.md section 2.

    The document is the authority for what the core digest covers, so the profile is
    compared against the text rather than against a second hand-written list.
    """
    text = (REPO_ROOT / "docs" / "core-contracts.md").read_text(encoding="utf-8")
    marker = "payload_hash只覆盖"
    start = text.index(marker)
    opening = text.index("{", start)
    closing = text.index("}", opening)
    return set(re.findall(r"[a-z_]+", text[opening + 1 : closing]))


def test_profile_is_core_v12(profile: CoreProfile) -> None:
    assert profile.profile_id == "core-v1.2"


def test_profile_names_its_authority_documents(profile: CoreProfile) -> None:
    for relative in profile.authority:
        assert (REPO_ROOT / relative).is_file(), f"authority document {relative} is missing"


def test_core_services_are_three_java_processes_and_one_agent(profile: CoreProfile) -> None:
    assert profile.core_service_names == ("gateway", "case-service", "commerce-service", "agent")


def test_languages_follow_the_core_deployment(profile: CoreProfile) -> None:
    assert profile.language_of("case-service") == "java"
    assert profile.language_of("commerce-service") == "java"
    assert profile.language_of("gateway") == "java"
    assert profile.language_of("agent") == "python"


def test_fulfillment_is_compat_only_and_not_core(profile: CoreProfile) -> None:
    assert "fulfillment-service" in profile.compat_only_services
    assert not profile.is_core_service("fulfillment-service")


def test_nacos_and_the_observability_stack_are_not_core_requirements(profile: CoreProfile) -> None:
    assert {"nacos", "sentinel"} <= set(profile.not_required)
    assert any("prometheus" in name for name in profile.not_required)


def test_only_refund_is_a_core_action(profile: CoreProfile) -> None:
    assert profile.allowed_actions == ("REFUND",)


def test_reship_still_exists_in_the_compat_enums_but_is_not_core(profile: CoreProfile) -> None:
    # The compat baseline keeps RESHIP so the old fixtures stay meaningful ...
    assert "RESHIP" in {member.value for member in enums.Action}
    # ... while the core profile must not grant it as an executable action.
    assert "RESHIP" not in profile.allowed_actions
    assert "reship" in profile.deferred_capabilities


def test_core_refund_targets_commerce_only(profile: CoreProfile) -> None:
    assert profile.allowed_target_services == ("commerce-service",)


def test_entitlement_and_address_hash_are_not_core_payload_fields(profile: CoreProfile) -> None:
    assert "entitlement_id" not in profile.payload_hash_fields
    assert "address_hash" not in profile.payload_hash_fields


def test_payload_hash_fields_match_the_authority_document(profile: CoreProfile) -> None:
    fields = set(profile.payload_hash_fields)
    assert fields == _authority_hash_fields()
    assert len(profile.payload_hash_fields) == 12


def test_payload_hash_covers_identity_and_authority_facts(profile: CoreProfile) -> None:
    required = {
        "operation_id",
        "case_id",
        "authorization_id",
        "input_revision",
        "line_id",
        "merchant_id",
        "action",
        "quantity",
        "currency",
        "amount_minor",
        "policy_version",
        "target_service",
    }
    assert set(profile.payload_hash_fields) == required


def test_wire_versions_separate_core_from_the_old_baseline(profile: CoreProfile) -> None:
    assert profile.command_schema_version == 2
    assert profile.envelope_schema_version == 2
    assert profile.proposal_schema_version == 2
    # The harness manifest is not a business command; core-contracts.md keeps it at 1.
    assert profile.manifest_schema_version == 1


def test_topics_are_the_core_v2_topics(profile: CoreProfile) -> None:
    assert profile.topics == {"case": "rf.case.core.v2", "commerce": "rf.commerce.core.v2"}


def test_core_event_names_are_unchanged_from_the_reliable_refund_set(profile: CoreProfile) -> None:
    assert set(profile.event_types) == {
        "RefundRequested",
        "RefundSucceeded",
        "RefundFailed",
        "RefundUnknown",
    }


def test_amount_bounds_are_exact_integer_bounds(profile: CoreProfile) -> None:
    assert profile.amount_min_minor == 1
    assert profile.amount_max_minor == 1_000_000_000
    assert profile.currency == "CNY"
    assert profile.max_exact_integer == 2**53 - 1


def test_every_deferred_capability_is_named_and_not_granted(profile: CoreProfile) -> None:
    missing = [capability for capability in DEFERRED if capability not in profile.deferred_capabilities]
    assert missing == [], f"deferred capabilities not listed in the core profile: {missing}"


def test_deferred_capabilities_do_not_leak_into_the_allowed_action_set(profile: CoreProfile) -> None:
    allowed = set(profile.allowed_actions)
    leaked = sorted(capability for capability in profile.deferred_capabilities if capability.upper() in allowed)
    assert leaked == []


def test_old_compat_baseline_is_still_present(profile: CoreProfile) -> None:
    for relative in COMPAT_OPENAPI + SCHEMA_FILES:
        assert (REPO_ROOT / relative).is_file(), f"compat asset {relative} was removed by the migration"
    assert (REPO_ROOT / "contracts/fixtures/examples/valid.json").is_file()
    assert (REPO_ROOT / "contracts/fixtures/reject/reject.json").is_file()


def test_missing_section_is_refused(tmp_path: Path) -> None:
    document: dict[str, Any] = json.loads((REPO_ROOT / PROFILE_PATH).read_text(encoding="utf-8"))
    del document["protocol"]
    broken = tmp_path / "profile.json"
    broken.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CoreProfileError, match="protocol"):
        load_core_profile(broken)


def test_missing_file_is_refused_with_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(CoreProfileError, match="core profile"):
        load_core_profile(tmp_path / "absent.json")


def test_unknown_action_is_refused(profile: CoreProfile) -> None:
    profile.require_action("REFUND")
    with pytest.raises(CoreProfileError, match="RESHIP"):
        profile.require_action("RESHIP")


def test_unknown_service_is_refused(profile: CoreProfile) -> None:
    profile.require_core_service("case-service")
    with pytest.raises(CoreProfileError, match="fulfillment-service"):
        profile.require_core_service("fulfillment-service")