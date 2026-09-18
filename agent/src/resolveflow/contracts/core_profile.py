"""The core-v1.2 deployment profile: the machine-readable allowlist for the core scope.

docs/core-scope.md narrows the project to one main chain and names what is deferred;
docs/core-contracts.md fixes the wire versions that belong to the core protocol. This
module turns that profile into something the code can actually be held to: a producer
asks for an allowed action instead of hard-coding ``REFUND``, and a test can prove that a
capability which exists only in the T02 compat baseline (RESHIP, entitlement
commit/release, cancel before start) was *not* granted by core.

The profile describes the target, not progress. It says which capabilities core grants;
it does not claim that the core schemas or routes have been implemented.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resolveflow.contracts._schemaio import REPO_ROOT

__all__ = [
    "CORE_PROFILE_PATH",
    "CoreProfile",
    "CoreProfileError",
    "load_core_profile",
]

#: Where the profile lives, relative to the repository root.
CORE_PROFILE_PATH = "contracts/core/profile.json"

_REQUIRED_SECTIONS = ("profile", "authority", "deployment", "protocol", "capabilities", "limits")
_REQUIRED_VERSIONS = (
    "command_schema_version",
    "envelope_schema_version",
    "proposal_schema_version",
    "manifest_schema_version",
)


class CoreProfileError(Exception):
    """The core profile is missing, malformed, or asked for something it does not allow."""


@dataclass(frozen=True)
class CoreProfile:
    """A validated view of ``contracts/core/profile.json``."""

    document: Mapping[str, Any]

    # ---------------------------------------------------------------- deployment

    @property
    def profile_id(self) -> str:
        return str(self.document["profile"])

    @property
    def authority(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.document["authority"])

    @property
    def core_service_names(self) -> tuple[str, ...]:
        return tuple(str(service["name"]) for service in self.document["deployment"]["core_services"])

    @property
    def compat_only_services(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["deployment"]["compat_only_services"])

    @property
    def not_required(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["deployment"]["not_required"])

    def is_core_service(self, service: str) -> bool:
        return service in self.core_service_names

    def language_of(self, service: str) -> str:
        for entry in self.document["deployment"]["core_services"]:
            if entry["name"] == service:
                return str(entry["language"])
        raise CoreProfileError(f"{service!r} is not a core service; core services are {self.core_service_names}")

    def require_core_service(self, service: str) -> str:
        """Return ``service`` unchanged, or refuse it the way a request body would be refused."""
        if not self.is_core_service(service):
            raise CoreProfileError(
                f"{service!r} is not a core service. Core: {self.core_service_names}. "
                f"Compat-only (not deployed in core): {self.compat_only_services}"
            )
        return service

    # ------------------------------------------------------------------ protocol

    def _version(self, key: str) -> int:
        return int(self.document["protocol"][key])

    @property
    def command_schema_version(self) -> int:
        return self._version("command_schema_version")

    @property
    def envelope_schema_version(self) -> int:
        return self._version("envelope_schema_version")

    @property
    def proposal_schema_version(self) -> int:
        return self._version("proposal_schema_version")

    @property
    def manifest_schema_version(self) -> int:
        return self._version("manifest_schema_version")

    @property
    def topics(self) -> dict[str, str]:
        return {str(key): str(value) for key, value in self.document["protocol"]["topics"].items()}

    @property
    def event_types(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["protocol"]["event_types"])

    @property
    def payload_hash_fields(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["protocol"]["payload_hash_fields"])

    @property
    def callback_kinds(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["protocol"]["callback_kinds"])

    @property
    def callback_dispositions(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["protocol"]["callback_dispositions"])

    @property
    def questions_max(self) -> int:
        return int(self.document["protocol"]["questions_max"])

    # -------------------------------------------------------------- capabilities

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["capabilities"]["allowed_actions"])

    @property
    def allowed_target_services(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.document["capabilities"]["allowed_target_services"])

    @property
    def deferred_capabilities(self) -> frozenset[str]:
        return frozenset(str(name) for name in self.document["capabilities"]["deferred"])

    def require_action(self, action: str) -> str:
        """Return ``action`` unchanged when core grants it, else refuse it by name."""
        if action not in self.allowed_actions:
            raise CoreProfileError(
                f"action {action!r} is not granted by the core profile; core allows {self.allowed_actions}. "
                f"Deferred capabilities: {sorted(self.deferred_capabilities)}"
            )
        return action

    # -------------------------------------------------------------------- limits

    def _limit(self, key: str) -> int:
        return int(self.document["limits"][key])

    @property
    def amount_min_minor(self) -> int:
        return self._limit("amount_min_minor")

    @property
    def amount_max_minor(self) -> int:
        return self._limit("amount_max_minor")

    @property
    def currency(self) -> str:
        return str(self.document["limits"]["currency"])

    @property
    def max_exact_integer(self) -> int:
        return self._limit("max_exact_integer")


def _validate(document: Mapping[str, Any], origin: Path) -> None:
    """Refuse a profile that cannot answer the questions the code asks of it."""
    for section in _REQUIRED_SECTIONS:
        if section not in document:
            raise CoreProfileError(f"core profile {origin} is missing section {section!r}")

    deployment = document["deployment"]
    for key in ("core_services", "compat_only_services", "not_required"):
        if not deployment.get(key):
            raise CoreProfileError(f"core profile {origin} declares no {key!r}")
    for service in deployment["core_services"]:
        if not service.get("name") or not service.get("language"):
            raise CoreProfileError(f"core profile {origin} has a core service without name/language: {service!r}")

    protocol = document["protocol"]
    for key in _REQUIRED_VERSIONS:
        if not isinstance(protocol.get(key), int):
            raise CoreProfileError(f"core profile {origin} has no integer {key!r}")
    if set(protocol.get("topics", {})) != {"case", "commerce"}:
        raise CoreProfileError(f"core profile {origin} must name the case and commerce topics")
    if not protocol.get("payload_hash_fields"):
        raise CoreProfileError(f"core profile {origin} declares no payload_hash_fields")

    capabilities = document["capabilities"]
    if not capabilities.get("allowed_actions") or not capabilities.get("allowed_target_services"):
        raise CoreProfileError(f"core profile {origin} declares no allowed actions or target services")
    if not capabilities.get("deferred"):
        raise CoreProfileError(f"core profile {origin} lists no deferred capabilities")

    limits = document["limits"]
    for key in ("amount_min_minor", "amount_max_minor", "currency", "max_exact_integer"):
        if key not in limits:
            raise CoreProfileError(f"core profile {origin} is missing limit {key!r}")


def load_core_profile(path: str | Path | None = None) -> CoreProfile:
    """Load and validate the core profile.

    ``path`` exists so a test can point at a deliberately broken document; production
    callers take the repository copy.
    """
    origin = Path(path) if path is not None else REPO_ROOT / CORE_PROFILE_PATH
    if not origin.is_file():
        raise CoreProfileError(f"core profile not found: {origin}")
    try:
        document = json.loads(origin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CoreProfileError(f"core profile {origin} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise CoreProfileError(f"core profile {origin} must be a JSON object")
    _validate(document, origin)
    return CoreProfile(document=document)