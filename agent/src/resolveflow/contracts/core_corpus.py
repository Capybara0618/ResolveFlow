"""The core-v1.2 fixture corpus: where each core fixture is validated, and how its
placeholders are filled.

Sibling of ``resolveflow.contracts.corpus`` rather than a variant of it. The two corpora
have different schemas, different signing key sets and different field sets, so one
shared validator map would let a core fixture be checked against a compat schema. The
section -> schema map therefore lives here, in code, for the same reason the compat map
does: a fixture must not be able to pick its own (possibly laxer) validator.

Placeholders are **recomputed, never frozen into a checked-in file**. An Ed25519
signature is deterministic, and ``payload_hash`` is a pure function of the command's
twelve fields, so the corpus leaves ``PLACEHOLDER_*`` tokens and this module fills them
from the authorities (docs/core-contracts.md:17 and docs/core-contracts.md:19). A stale
copy of a digest on disk is exactly what lets a fixture look self-consistent while
disagreeing with the hasher.
"""

from __future__ import annotations

import copy
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, load_json, validator_bundle
from resolveflow.contracts.canonical import CanonicalizationError, payload_hash
from resolveflow.contracts.events import EventSignatureError, sign_core_envelope, verify_core_envelope
from resolveflow.contracts.fixtures import PLACEHOLDER_PREFIX, collect_placeholders, resolve_instance, substitute_values

__all__ = [
    "CORE_CORPUS_PATH",
    "CORE_EXPECTED_PATH",
    "CORE_REJECT_PATH",
    "CORE_REJECT_TARGETS",
    "CORE_SCHEMA_SECTIONS",
    "SIGNING_KEY_ID",
    "SUPPORT_SECTIONS",
    "CoreCorpusError",
    "computed_placeholder_values",
    "core_placeholder_tokens",
    "core_signing_keys",
    "load_core_corpus",
    "load_core_reject_corpus",
    "resolve_core_instance",
    "resolve_core_negative_instance",
    "strip_annotations",
    "validate_core_corpus",
    "validate_core_invalid_payloads",
    "validate_core_reject_corpus",
]

CORE_CORPUS_PATH = "contracts/core/fixtures/valid.json"
CORE_REJECT_PATH = "contracts/core/fixtures/reject.json"
CORE_EXPECTED_PATH = "contracts/core/fixtures/expected.json"

#: Schema every section's entries must satisfy. The URNs are written out rather than read
#: from the files so the corpus test can compare them against the ids actually on disk:
#: if they were derived, that comparison could never fail.
CORE_COMMAND = "urn:resolveflow:core:refund-command:v2"
CORE_ENVELOPE = "urn:resolveflow:core:event-envelope:v2"
CORE_PROPOSAL = "urn:resolveflow:core:agent-proposal:v2"

CORE_SCHEMA_SECTIONS: dict[str, str] = {
    "execution_commands": CORE_COMMAND,
    "message_envelopes": CORE_ENVELOPE,
    "agent_proposals": CORE_PROPOSAL,
}

#: Blocks that support the fixtures instead of being fixtures: the shared objects other
#: entries reference, and the fixture-only signing keys. They are declared so a test can
#: assert the corpus has exactly the sections it is supposed to have.
SUPPORT_SECTIONS = ("components", "signing_keys")

SIGNING_KEY_ID = "core-fixture-key-1"

#: The schema each negative section's instances must be refused by, or ``None`` when the
#: refusal has to come from the hasher because the rule (integer money, the 2^53-1 bound,
#: which fields a digest covers) is not expressible as a JSON Schema constraint on the
#: digest input.
CORE_REJECT_TARGETS: dict[str, str | None] = {
    "execution_commands": CORE_COMMAND,
    "event_envelopes": CORE_ENVELOPE,
    "agent_proposals": CORE_PROPOSAL,
    "canonical_payloads": None,
}


class CoreCorpusError(ValueError):
    """A core fixture does not mean what it claims, or a placeholder cannot be filled."""


def load_core_corpus() -> dict[str, Any]:
    return load_json(CORE_CORPUS_PATH)


def _fixtures_in(corpus: dict[str, Any], section: str) -> list[str]:
    """The fixture names in a section, without the ``_``-prefixed annotations."""
    entries = corpus[section]
    if not isinstance(entries, dict):
        raise CoreCorpusError(f"core corpus section '{section}' must be an object")
    return sorted(name for name in entries if not name.startswith("_"))


def _require_placeholder(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.startswith(PLACEHOLDER_PREFIX):
        raise CoreCorpusError(f"{where} must declare a {PLACEHOLDER_PREFIX}* token, found {value!r}")
    return value


def core_signing_keys(corpus: dict[str, Any]) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """The fixture key pair, checked against the public key the corpus declares.

    The check is the point: a fixture key that does not match its declared public key
    would still sign, and every signature test would pass while proving nothing about
    which key produced them.
    """
    entry = corpus["signing_keys"][SIGNING_KEY_ID]
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(entry["private_seed_hex"]))
    public_key = private_key.public_key()
    derived = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    declared = entry["public_key_hex"]
    if derived != declared:
        raise CoreCorpusError(
            f"signing_keys.{SIGNING_KEY_ID}.public_key_hex is {declared}, but the seed derives {derived}"
        )
    return private_key, public_key


def computed_placeholder_values(
    corpus: dict[str, Any],
    private_key: Ed25519PrivateKey | None = None,
) -> dict[str, str]:
    """Fill every ``PLACEHOLDER_*`` token the corpus declares.

    Order matters: a command's ``payload_hash`` is computed first, because an envelope
    that carries that command is signed over its payload - signing before the digest was
    substituted would sign the literal token.
    """
    key = private_key if private_key is not None else core_signing_keys(corpus)[0]
    values: dict[str, str] = {}
    components = corpus["components"]
    for name in _fixtures_in(corpus, "components"):
        component = components[name]
        if "action" not in component:
            continue
        token = _require_placeholder(component.get("payload_hash"), f"components.{name}.payload_hash")
        values[token] = payload_hash(component)
    for name in _fixtures_in(corpus, "message_envelopes"):
        entry = corpus["message_envelopes"][name]
        token = _require_placeholder(entry.get("signature"), f"message_envelopes.{name}.signature")
        # The envelope's own token is dropped before substituting: it is the value being
        # computed here, and the signing input never covers ``signature`` anyway.
        unsigned = {key: value for key, value in entry.items() if key != "signature"}
        resolved = substitute_values(_resolve_reference(corpus, unsigned, f"message_envelopes.{name}"), values)
        values[token] = sign_core_envelope(resolved, key)
    return values


def _lookup(corpus: dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted corpus path such as ``components.proposalRefund``."""
    node: Any = corpus
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise CoreCorpusError(f"core fixture reference '{dotted}' does not resolve")
        node = node[part]
    return copy.deepcopy(node)


def strip_annotations(node: Any) -> Any:
    """Drop every ``_``-prefixed key, recursively.

    The compat resolver strips annotations only at the top level of the entry it is
    given, which is enough for a corpus that inlines its objects. Core fixtures reference
    shared components instead, and a referenced component carries its own ``_comment`` -
    so without this the annotation would travel into the instance and every schema here
    (all ``additionalProperties: false``) would reject a fixture that is otherwise fine.
    No wire field in this protocol starts with an underscore, so nothing real is dropped.
    """
    if isinstance(node, dict):
        return {
            key: strip_annotations(value)
            for key, value in node.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(node, list):
        return [strip_annotations(item) for item in node]
    return node


def _resolve_reference(corpus: dict[str, Any], entry: dict[str, Any], where: str) -> dict[str, Any]:
    """Inline an entry's references and strip annotations.

    Two reference forms are supported. A **nested** reference is the compat convention
    and is delegated to :func:`resolveflow.contracts.fixtures.resolve_instance`. A
    **top-level alias** - an entry whose whole body is ``{"_ref": "components.x"}`` -
    needs handling here, because the compat resolver drops every ``_``-prefixed key as an
    annotation and would silently return an empty fixture, which is a fixture that
    validates nothing. ``_ref`` is the one underscore key that means "replace me" rather
    than "read me".
    """
    if "_ref" in entry:
        unexpected = set(entry) - {"_ref", "_comment"}
        if unexpected:
            raise CoreCorpusError(f"core fixture {where} aliases {entry['_ref']!r} and cannot also set {unexpected}")
        referenced = _lookup(corpus, entry["_ref"])
        if not isinstance(referenced, dict):
            raise CoreCorpusError(f"core fixture {where} references a non-object at {entry['_ref']!r}")
        return strip_annotations(referenced)
    return strip_annotations(resolve_instance(entry, corpus))


def _resolve_entry(corpus: dict[str, Any], section: str, name: str) -> dict[str, Any]:
    entry = corpus[section][name]
    if not isinstance(entry, dict):
        raise CoreCorpusError(f"core fixture {section}.{name} must be an object")
    return _resolve_reference(corpus, entry, f"{section}.{name}")


def resolve_core_instance(
    corpus: dict[str, Any],
    section: str,
    name: str,
    values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One concrete fixture: references inlined, annotations dropped, placeholders filled."""
    if section not in CORE_SCHEMA_SECTIONS:
        raise CoreCorpusError(f"unknown core corpus section '{section}'; known: {sorted(CORE_SCHEMA_SECTIONS)}")
    if name not in _fixtures_in(corpus, section):
        raise CoreCorpusError(f"core corpus has no fixture {section}.{name}")
    resolved = _resolve_entry(corpus, section, name)
    filled = values if values is not None else computed_placeholder_values(corpus)
    return substitute_values(resolved, filled)


def core_placeholder_tokens(corpus: dict[str, Any]) -> set[str]:
    """Every ``PLACEHOLDER_*`` token the corpus file uses, annotations included."""
    return collect_placeholders(corpus)


# ----------------------------------------------------------------- the negative corpus


def load_core_reject_corpus() -> dict[str, Any]:
    return load_json(CORE_REJECT_PATH)


def _remove_path(instance: dict[str, Any], dotted: str) -> None:
    """Delete a dotted path, refusing a path that was not there.

    A silent no-op would turn "this fixture must lack ``payload.aggregate_version``" into
    a fixture that still has it - a negative case that tests nothing while looking
    deliberate.
    """
    parts = dotted.split(".")
    node: Any = instance
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise CoreCorpusError(f"negative fixture removes {dotted!r}, but {part!r} is not there")
        node = node[part]
    last = parts[-1]
    if not isinstance(node, dict) or last not in node:
        raise CoreCorpusError(f"negative fixture removes {dotted!r}, but it is not there")
    del node[last]


def _negative_instance(
    entry: dict[str, Any],
    valid: dict[str, Any],
    values: dict[str, str],
    where: str,
) -> dict[str, Any]:
    """Build one negative instance from a full object or from a named base plus a delta.

    A negative fixture is interesting for its delta, so most entries name a positive base
    and change one thing. Two forms are supported: ``instance`` (a complete object, for
    cases that share nothing with a positive fixture) and ``base`` plus ``overrides`` /
    ``remove``, where ``base`` is ``valid:<dotted path>`` into the positive corpus.
    """
    if "instance" in entry:
        candidate = copy.deepcopy(entry["instance"])
        if not isinstance(candidate, dict):
            raise CoreCorpusError(f"negative fixture {where}.instance must be an object")
        instance = strip_annotations(candidate)
    elif "base" in entry:
        prefix, _, path = str(entry["base"]).partition(":")
        if prefix != "valid" or not path:
            raise CoreCorpusError(
                f"negative fixture {where} names base {entry['base']!r}; only 'valid:<path>' is known"
            )
        referenced = _lookup(valid, path)
        if not isinstance(referenced, dict):
            raise CoreCorpusError(f"negative fixture {where} bases itself on a non-object at {path!r}")
        instance = strip_annotations(resolve_instance(referenced, valid))
    else:
        raise CoreCorpusError(f"negative fixture {where} must provide instance or base")
    instance = substitute_values(instance, values)
    for dotted in entry.get("remove", []):
        _remove_path(instance, dotted)
    overrides = entry.get("overrides", {})
    if not isinstance(overrides, dict):
        raise CoreCorpusError(f"negative fixture {where}.overrides must be an object")
    instance.update(overrides)
    return instance


def resolve_core_negative_instance(
    reject: dict[str, Any],
    section: str,
    name: str,
    valid: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One concrete negative instance, for tests that inspect the deltas themselves."""
    positive = valid if valid is not None else load_core_corpus()
    entries = reject[section]
    if not isinstance(entries, dict) or name not in entries:
        raise CoreCorpusError(f"negative corpus has no fixture {section}.{name}")
    entry = entries[name]
    if not isinstance(entry, dict):
        raise CoreCorpusError(f"negative fixture {section}.{name} must be an object")
    return _negative_instance(entry, positive, computed_placeholder_values(positive), f"{section}.{name}")


def validate_core_reject_corpus(
    reject: dict[str, Any] | None = None,
    valid: dict[str, Any] | None = None,
) -> list[str]:
    """Assert every negative fixture is refused by the schema its section names.

    Returns one line per fixture. A rejection that starts passing means the protocol
    regressed and the schema needs fixing - not the fixture.
    """
    document = reject if reject is not None else load_core_reject_corpus()
    positive = valid if valid is not None else load_core_corpus()
    values = computed_placeholder_values(positive)
    checked: list[str] = []
    for section, entries in document.items():
        if section.startswith("_"):
            continue
        if section not in CORE_REJECT_TARGETS:
            raise CoreCorpusError(f"negative corpus section '{section}' names no schema to be refused by")
        target = CORE_REJECT_TARGETS[section]
        if target is None:
            # Checked by the hasher rather than a schema; see validate_core_invalid_payloads.
            continue
        validator = validator_bundle(target, CORE_SCHEMA_FILES)
        if not isinstance(entries, dict):
            raise CoreCorpusError(f"negative corpus section '{section}' must be an object")
        for name in sorted(name for name in entries if not name.startswith("_")):
            entry = entries[name]
            if not isinstance(entry, dict):
                raise CoreCorpusError(f"negative fixture {section}.{name} must be an object")
            why = entry.get("why")
            if not isinstance(why, str) or not why:
                raise CoreCorpusError(f"negative fixture {section}.{name} does not say why it must be refused")
            instance = _negative_instance(entry, positive, values, f"{section}.{name}")
            if validator.accepts(instance):
                raise CoreCorpusError(
                    f"negative fixture {section}.{name} is accepted by {validator.name}, but it must be refused. "
                    f"Reason it exists: {why}"
                )
            checked.append(f"rejected as required: {section}.{name}")
    return checked


def validate_core_invalid_payloads(reject: dict[str, Any] | None = None) -> list[str]:
    """Prove every payload JSON Schema cannot describe is refused rather than hashed.

    A float amount, an integer past 2^53-1, a missing hashed field and an action whose
    field set is different cannot be expressed as a JSON Schema constraint on *the
    digest input*; they are checked by calling the hasher, the way a producer would. A
    payload that silently hashes is worse than one that hashes wrongly: both sides would
    agree on a digest for something that must not exist.
    """
    document = reject if reject is not None else load_core_reject_corpus()
    positive = load_core_corpus()
    values = computed_placeholder_values(positive)
    entries = document.get("canonical_payloads", {})
    if not isinstance(entries, dict):
        raise CoreCorpusError("negative corpus section 'canonical_payloads' must be an object")
    checked: list[str] = []
    for name in sorted(name for name in entries if not name.startswith("_")):
        entry = entries[name]
        why = entry.get("why")
        if not isinstance(why, str) or not why:
            raise CoreCorpusError(f"negative fixture canonical_payloads.{name} does not say why it must be refused")
        instance = _negative_instance(entry, positive, values, f"canonical_payloads.{name}")
        try:
            digest = payload_hash(instance)
        except CanonicalizationError:
            checked.append(f"refused by the hasher: canonical_payloads.{name}")
            continue
        raise CoreCorpusError(
            f"negative fixture canonical_payloads.{name} was hashed as {digest}, but it must be refused. "
            f"Reason it exists: {why}"
        )
    return checked


def validate_core_corpus(corpus: dict[str, Any] | None = None) -> list[str]:
    """Validate every positive fixture and verify every fixture signature.

    Returns one line per check performed, so a caller (or a report) can show what was
    actually covered rather than a bare pass. A fixture that fails raises instead of
    being skipped: a silent skip would leave the corpus without evidence.
    """
    document = corpus if corpus is not None else load_core_corpus()
    values = computed_placeholder_values(document)
    _, public_key = core_signing_keys(document)
    checked: list[str] = []
    for section, target in CORE_SCHEMA_SECTIONS.items():
        validator = validator_bundle(target, CORE_SCHEMA_FILES)
        for name in _fixtures_in(document, section):
            instance = resolve_core_instance(document, section, name, values)
            errors = validator.error_messages(instance)
            if errors:
                raise CoreCorpusError(
                    f"core fixture {section}.{name} does not satisfy {validator.name}:\n  " + "\n  ".join(errors)
                )
            checked.append(f"{section}.{name} -> {validator.name}")
    for name in _fixtures_in(document, "message_envelopes"):
        instance = resolve_core_instance(document, "message_envelopes", name, values)
        try:
            verify_core_envelope(instance, instance["signature"], public_key)
        except EventSignatureError as error:
            raise CoreCorpusError(
                f"core fixture message_envelopes.{name} is not signed by {SIGNING_KEY_ID}: {error}"
            ) from error
        checked.append(f"message_envelopes.{name} signature verified")
    return checked