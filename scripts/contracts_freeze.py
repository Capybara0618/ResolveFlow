#!/usr/bin/env python3
"""Regenerate (or verify) the frozen T02 expectations: contracts/fixtures/expected-*.json.

Run from anywhere:

    uv run --project agent --frozen python scripts/contracts_freeze.py
    uv run --project agent --frozen python scripts/contracts_freeze.py --check

Why a generator at all: docs/contracts.md:17 requires T02 to freeze both the signing
inputs and the resulting bytes, and docs/contracts.md:13 the same for the execution
payload hash. Hand-typing 64-character hashes into a JSON file is how those numbers
stop matching the fixtures they describe. Here the values are *computed* from the
corpus, and the corpus is validated in the same pass, so a fixture edit that changes a
hash cannot leave the frozen file stale.

The mapping from fixture to schema, and the validation and signing themselves, live in
``resolveflow.contracts.corpus`` rather than here, so the test suite checks exactly what
this script checks.

``--check`` recomputes everything and compares against the files on disk without
writing, which is what ``verify -Suite contracts`` runs. A fixture edited without
re-freezing, or a canonicalisation regression, therefore fails the suite instead of
quietly disagreeing with the frozen file.

Editing the corpus, or running this script without ``--check``, is the intended way to
re-freeze. Re-freezing because a test failed is not: a changed hash means either the
corpus changed on purpose or the canonicalisation regressed, and those need different
answers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Allow running the script directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent" / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from resolveflow.contracts._schemaio import REPO_ROOT, load_json  # noqa: E402
from resolveflow.contracts.corpus import (  # noqa: E402
    CorpusError,
    enum_groups,
    recompute_frozen_values,
    require_placeholder_coverage,
    sign_corpus_envelopes,
    validate_invalid_payloads,
    validate_negative_corpus,
    validate_valid_corpus,
)
from resolveflow.contracts.fixtures import (  # noqa: E402
    CORPUS_PATHS,
    GENERATED_PATHS,
    collect_placeholders,
)

#: A fixed test seed. The private key derived from it is a *fixture*, never a
#: deployment key: docs/contracts.md:17 mounts the real private key at runtime and keeps
#: it out of the repository. Anyone can reproduce this key, which is exactly what makes
#: the frozen signature verifiable in CI.
TEST_KEY_SEED = b"resolveflow-t02-event-signature-fixture-v1"
TEST_SIGNING_KEY_ID = "rf-case-events-2026-09"


def test_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(TEST_KEY_SEED).digest())


def placeholder_token(name: str) -> str:
    return f"PLACEHOLDER_{name.upper().replace('-', '_')}"


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def enum_expectations() -> dict[str, Any]:
    """Freeze every wire enum so a rename on one side fails a test on both."""
    return {
        "_comment": [
            "T02 frozen enum mapping. Java (com.resolveflow.shared.contract.ContractEnums) and Python (resolveflow.contracts.enums) both assert against this file.",
            "A member renamed on one side therefore fails a test on both, instead of producing an unroutable action at runtime.",
            "Regenerate with: uv run --project agent --frozen python scripts/contracts_freeze.py",
        ],
        "enums": enum_groups(),
    }


def build() -> dict[str, str]:
    """Validate the whole corpus and return ``path -> file text`` for the frozen files."""
    canonical = load_json(CORPUS_PATHS["canonical"])
    valid = load_json(CORPUS_PATHS["valid"])
    reject = load_json(CORPUS_PATHS["reject"])
    private_key = test_private_key()
    public_key = private_key.public_key()

    payload_hashes, content_hashes, canonical_texts = recompute_frozen_values(canonical)

    # Placeholder table, hashes first. A placeholder exists so a fixture can refer to a
    # frozen digest instead of repeating 64 characters. Only the payloads some fixture
    # actually embeds need one: the remaining canonical payloads are hash *inputs* with
    # nothing to reference, and are still frozen below and asserted by both languages.
    # Requiring a placeholder for every one of them would mean inventing a use for it.
    referenced_tokens = collect_placeholders(valid) | collect_placeholders(canonical)
    values: dict[str, str] = {
        placeholder_token(name): digest
        for name, digest in payload_hashes.items()
        if placeholder_token(name) in referenced_tokens
    }

    # 1) Every positive fixture against the schema or OpenAPI component it names.
    validated = validate_valid_corpus(valid, values)

    # 2) Sign the case envelopes and validate every envelope document. Signature values
    #    are recorded in the placeholder table as each one is produced, so the table and
    #    the frozen signatures cannot disagree.
    signing_inputs, signatures = sign_corpus_envelopes(valid, values, private_key, TEST_SIGNING_KEY_ID)
    for name in valid["message_envelope"]:
        validated.append(
            f"validated message_envelope.{name}"
            + ("" if name in signatures else " (unsigned result event)")
        )
    for line in validated:
        print(line)

    # 3) Every negative fixture must actually be refused by the schema it names, and
    #    every payload a JSON Schema cannot rule out must be refused by the hasher.
    refused = validate_negative_corpus(reject) + validate_invalid_payloads(canonical)
    for line in refused:
        print(line)
    print(f"{len(refused)} fixtures refused, {len(validated)} positive fixtures validated")

    # 4) Freeze. Coverage spans both corpus documents, since either may reference a
    #    frozen value.
    require_placeholder_coverage({"valid": valid, "canonical": canonical}, values)

    hashes = {
        "_comment": [
            "Frozen T02 expectations. Generated by scripts/contracts_freeze.py; do not hand-edit.",
            "docs/contracts.md:17 requires both the signing input and the resulting bytes to be fixed by a cross-language test, and the same for the execution payload hash.",
            "Java (com.resolveflow.shared.contract) and Python (resolveflow.contracts) each reproduce these values from contracts/fixtures/examples/*.json. Either side failing means the two implementations disagree.",
            "The signing keys below are derived from a public fixture seed and exist only so the frozen signature can be verified in CI. They are not deployment keys.",
            "signing_inputs covers every envelope in the corpus, signed or not: for an unsigned result event it is the byte sequence a producer would sign, which is what makes the normalisation rule testable.",
        ],
        "algorithm": {
            "payload_hash": "SHA-256 over RFC 8785 canonical JSON of the documented field set",
            "event_signature": "Ed25519 (RFC 8032) over the canonical envelope with `signature` excluded",
        },
        "signing_keys": {
            "key_id": TEST_SIGNING_KEY_ID,
            "seed_sha256_preimage": TEST_KEY_SEED.decode("ascii"),
            "private_key_pkcs8_base64": base64.b64encode(
                private_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            ).decode("ascii"),
            "public_key_spki_base64": base64.b64encode(
                public_key.public_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).decode("ascii"),
        },
        "execution_payload_hashes": payload_hashes,
        "content_hashes": content_hashes,
        "canonical_documents": canonical_texts,
        "signing_inputs": signing_inputs,
        "event_signatures": signatures,
        "placeholder_values": values,
    }

    return {
        GENERATED_PATHS["hashes"]: render_json(hashes),
        GENERATED_PATHS["enums"]: render_json(enum_expectations()),
    }


def main(argv: list[str]) -> int:
    check_only = "--check" in argv[1:]
    unexpected = [arg for arg in argv[1:] if arg != "--check"]
    if unexpected:
        print(f"unknown argument(s): {' '.join(unexpected)}", file=sys.stderr)
        return 64

    try:
        documents = build()
    except CorpusError as error:
        print(f"corpus is not usable: {error}", file=sys.stderr)
        return 1

    if check_only:
        stale = []
        for relative, text in documents.items():
            path = REPO_ROOT / relative
            if not path.exists():
                stale.append(f"{relative}: missing")
            elif path.read_text(encoding="utf-8") != text:
                stale.append(f"{relative}: differs from the freshly computed values")
        if stale:
            print("frozen expectations are stale:", file=sys.stderr)
            for line in stale:
                print(f"  - {line}", file=sys.stderr)
            print(
                "Re-run without --check only if the corpus changed on purpose; otherwise the "
                "canonicalisation regressed.",
                file=sys.stderr,
            )
            return 1
        print("frozen expectations match the corpus")
        return 0

    for relative, text in documents.items():
        path = REPO_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {relative} ({len(text)} bytes)")
    print("frozen expectations regenerated and every fixture validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))