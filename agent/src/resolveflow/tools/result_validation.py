"""Validate business payloads before they can become cited observations."""

from functools import lru_cache
from typing import Any

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, component_validator

COMPONENTS = {
    "get_order_context": ("commerce", "LineContext"),
    "get_refund_status": ("commerce", "LineRefundStatus"),
    "get_shipment_trace": ("commerce", "ShipmentSnapshot"),
    "get_case_evidence": ("case", "EvidenceListResponse"),
    "get_policy_manifest": ("case", "PolicyManifestResponse"),
}


class InvalidToolResult(Exception):
    def __init__(self, message: str, code: str = "TOOL_RESULT_INVALID"):
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=5)
def _validator(tool: str) -> Any:
    service, component = COMPONENTS[tool]
    return component_validator(service, component, "contracts/core", CORE_SCHEMA_FILES).validator


def validate_result(tool: str, body: dict[str, Any], *, line_id: str | None, case_id: str | None) -> None:
    def check_numbers(value: Any, path: str = "<root>") -> None:
        # These five contracts use integer minor amounts/versions, never floats.
        # JSON Schema considers 1.0 an integer; do not silently coerce wire values.
        if isinstance(value, float):
            raise InvalidToolResult(f"{tool} result requires strict integer value: {path}")
        if isinstance(value, dict):
            for key, child in value.items():
                check_numbers(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_numbers(child, f"{path}/{index}")

    check_numbers(body)
    errors = list(_validator(tool).iter_errors(body))
    if errors:
        # Field + failed constraint, never echo source contents or arbitrary exception text.
        detail = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.validator}" for e in errors[:4])
        raise InvalidToolResult(f"{tool} result violates core response contract: {detail}")
    expected = case_id if tool == "get_case_evidence" else line_id
    key = "case_id" if tool == "get_case_evidence" else "line_id"
    if key in body and body[key] != expected:
        raise InvalidToolResult(f"{tool} result does not match the bound {key}", "SOURCE_MISMATCH")
