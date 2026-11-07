"""Project frozen synthetic inputs onto the current wire without changing archive bytes.

This is an offline test adapter, never an account migration or a strict replay decoder.
Real buyers are resolved by buyer_identity_migration.py from persisted account bindings.
"""
from __future__ import annotations

from typing import Any


def project_identity(value: Any) -> Any:
    if isinstance(value, list):
        return [project_identity(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: project_identity(item) for key, item in value.items() if key != "customer_id"}
    if "customer_id" in value:
        if "buyer_id" in value and value["buyer_id"] != value["customer_id"]:
            raise ValueError("Ambiguous synthetic identity projection")
        result["buyer_id"] = value["customer_id"]
    return result
