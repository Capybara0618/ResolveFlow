"""C00.2c-2b: the core negative corpus.

Every entry in ``contracts/core/fixtures/reject.json`` claims a fixture that the protocol
must refuse, and says why. The tests here hold that claim to three standards: the refusal
must actually happen, the reason must cite an authority rather than assert an opinion, and
the corpus must not be able to quietly stop testing what it says it tests (an override
that no longer changes anything, a ``remove`` of a field that was never there).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, schema_registry
from resolveflow.contracts.core_corpus import (
    CORE_REJECT_TARGETS,
    CORE_SCHEMA_SECTIONS,
    CoreCorpusError,
    load_core_reject_corpus,
    resolve_core_negative_instance,
    validate_core_invalid_payloads,
    validate_core_reject_corpus,
)

SCHEMA_SECTIONS = [
    section for section, target in CORE_REJECT_TARGETS.items() if target is not None
]
HASHER_SECTION = "canonical_payloads"


@pytest.fixture()
def reject() -> dict[str, Any]:
    return load_core_reject_corpus()


def entries_of(reject: dict[str, Any], section: str) -> list[str]:
    return sorted(name for name in reject[section] if not name.startswith("_"))


# ------------------------------------------------------------------- shape of the file


def test_the_reject_corpus_has_exactly_the_sections_it_declares(reject: dict[str, Any]) -> None:
    present = {key for key in reject if not key.startswith("_")}
    assert present == set(CORE_REJECT_TARGETS)


def test_the_negative_sections_mirror_the_positive_ones(reject: dict[str, Any]) -> None:
    """A negative corpus for a schema the positive corpus does not cover would be a typo."""
    for section, target in CORE_REJECT_TARGETS.items():
        if target is None:
            continue
        assert target in set(CORE_SCHEMA_SECTIONS.values()), (
            f"{section} names {target}, which no positive section covers"
        )


def test_every_negative_section_has_at_least_one_fixture(reject: dict[str, Any]) -> None:
    for section in CORE_REJECT_TARGETS:
        assert entries_of(reject, section), f"section {section} is empty"


def test_every_refusal_says_why_and_cites_an_authority(reject: dict[str, Any]) -> None:
    for section in CORE_REJECT_TARGETS:
        for name in entries_of(reject, section):
            why = reject[section][name].get("why")
            assert isinstance(why, str) and why, f"{section}.{name} has no reason"
            assert "docs/" in why, f"{section}.{name} gives a reason without citing an authority: {why}"


def test_every_core_schema_has_negative_coverage(reject: dict[str, Any]) -> None:
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    targets = {target for target in CORE_REJECT_TARGETS.values() if target is not None}
    assert targets == {document["$id"] for document in documents.values()}


# ------------------------------------------------------------------- the refusals


def test_every_negative_fixture_is_refused() -> None:
    checked = validate_core_reject_corpus()
    assert len(checked) >= 40, checked
    covered = {line.split(": ", 1)[1] for line in checked}
    corpus = load_core_reject_corpus()
    for section in SCHEMA_SECTIONS:
        for name in entries_of(corpus, section):
            assert f"{section}.{name}" in covered, f"{section}.{name} was not checked"


def test_every_unhashable_payload_is_refused_by_the_hasher() -> None:
    checked = validate_core_invalid_payloads()
    assert len(checked) == len(entries_of(load_core_reject_corpus(), HASHER_SECTION))
    assert all(line.startswith("refused by the hasher") for line in checked)


def test_the_two_specific_cases_this_step_exists_for(reject: dict[str, Any]) -> None:
    """The two shapes a schema alone would have accepted, kept as named evidence."""
    command = resolve_core_negative_instance(reject, "execution_commands", "entitlement_id_present")
    assert "entitlement_id" in command
    proposal = resolve_core_negative_instance(reject, "agent_proposals", "source_ref_is_url")
    assert proposal["evidence_refs"][0]["source_ref"].startswith("https://")


def test_no_negative_instance_keeps_a_literal_placeholder(reject: dict[str, Any]) -> None:
    for section in CORE_REJECT_TARGETS:
        for name in entries_of(reject, section):
            instance = resolve_core_negative_instance(reject, section, name)
            assert "PLACEHOLDER_" not in str(instance), f"{section}.{name} kept an unresolved token"


# ------------------------------------------------------- the corpus cannot go quiet


def test_each_delta_is_necessary_and_sufficient(reject: dict[str, Any]) -> None:
    """Refusal "for some reason" is not evidence: the stated change must be the reason.

    For every entry built on a positive base, the mutated instance must be refused *and*
    the untouched base must still be accepted. An entry whose base is already invalid
    would otherwise pass forever while testing something other than what its ``why``
    claims.
    """
    from resolveflow.contracts._schemaio import validator_bundle

    for section in SCHEMA_SECTIONS:
        validator = validator_bundle(CORE_REJECT_TARGETS[section] or "", CORE_SCHEMA_FILES)
        for name in entries_of(reject, section):
            entry = reject[section][name]
            if "base" not in entry:
                continue
            assert not validator.accepts(resolve_core_negative_instance(reject, section, name)), (
                f"{section}.{name} was not refused at all"
            )
            restored = copy.deepcopy(entry)
            restored.pop("overrides", None)
            restored.pop("remove", None)
            mini = {section: {name: restored}}
            base_instance = resolve_core_negative_instance(mini, section, name)
            errors = validator.error_messages(base_instance)
            assert not errors, f"{section}.{name} bases itself on something {validator.name} already rejects: {errors}"


def test_each_unhashable_delta_is_necessary_and_sufficient(reject: dict[str, Any]) -> None:
    from resolveflow.contracts.canonical import payload_hash

    for name in entries_of(reject, HASHER_SECTION):
        entry = reject[HASHER_SECTION][name]
        restored = copy.deepcopy(entry)
        restored.pop("overrides", None)
        restored.pop("remove", None)
        mini = {HASHER_SECTION: {name: restored}}
        base_instance = resolve_core_negative_instance(mini, HASHER_SECTION, name)
        assert payload_hash(base_instance), f"{HASHER_SECTION}.{name} bases itself on a payload the hasher refuses"


def test_a_negative_fixture_that_starts_passing_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    del broken["execution_commands"]["reship_action"]["overrides"]
    with pytest.raises(CoreCorpusError, match="must be refused"):
        validate_core_reject_corpus(broken)


def test_removing_a_field_that_is_not_there_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    broken["execution_commands"]["missing_payload_hash"]["remove"] = ["no_such_field"]
    with pytest.raises(CoreCorpusError, match="not there"):
        resolve_core_negative_instance(broken, "execution_commands", "missing_payload_hash")


def test_a_payload_that_hashes_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    broken[HASHER_SECTION]["float_amount"]["overrides"] = {"amount_minor": 2599}
    with pytest.raises(CoreCorpusError, match="was hashed as"):
        validate_core_invalid_payloads(broken)


def test_a_missing_reason_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    del broken["agent_proposals"]["reship_action"]["why"]
    with pytest.raises(CoreCorpusError, match="does not say why"):
        validate_core_reject_corpus(broken)


def test_an_unknown_negative_section_is_reported(reject: dict[str, Any]) -> None:
    broken = {**reject, "reship_commands": {"x": {"why": "docs/core-scope.md:17", "instance": {}}}}
    with pytest.raises(CoreCorpusError, match="names no schema"):
        validate_core_reject_corpus(broken)


def test_an_unknown_base_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    broken["execution_commands"]["reship_action"]["base"] = "compat:components.refundCommandLostParcel"
    with pytest.raises(CoreCorpusError, match="only 'valid:"):
        resolve_core_negative_instance(broken, "execution_commands", "reship_action")


def test_a_base_that_does_not_resolve_is_reported(reject: dict[str, Any]) -> None:
    broken = copy.deepcopy(reject)
    broken["execution_commands"]["reship_action"]["base"] = "valid:components.noSuchComponent"
    with pytest.raises(CoreCorpusError, match="does not resolve"):
        resolve_core_negative_instance(broken, "execution_commands", "reship_action")