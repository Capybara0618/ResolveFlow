import json

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi


def test_platform_operations_wire_is_closed_and_never_accepts_private_fields():
    fixtures = json.loads((REPO_ROOT / "contracts/core/fixtures/support-operations.json").read_text(encoding="utf-8"))
    for name, value in fixtures.items():
        validator = component_validator("case", name, "contracts/core")
        assert validator.accepts(value), validator.error_messages(value)
        assert not validator.accepts({**value, "private_messages": []})
    detail = fixtures["SupportOperationsDetail"]
    validator = component_validator("case", "SupportOperationsDetail", "contracts/core")
    assert not validator.accepts({**detail, "events": [{**detail["events"][0], "payload_json": {"text": "private"}}]})
    assert not validator.accepts({**detail, "run": {**detail["run"], "prompt": "private"}})
    assert validator.accepts({**detail, "run": {**detail["run"], "model_requests": None}})


def test_operations_routes_are_read_only_and_require_a_current_user_session():
    doc = load_openapi("case", "contracts/core")
    for path in ("/api/v1/platform/support-runs", "/api/v1/platform/support-runs/{id}"):
        assert set(doc["paths"][path]) == {"get"}
        operation = doc["paths"][path]["get"]
        assert operation["security"] == [{"bearerAuth": []}]
        assert {"401", "403"} <= operation["responses"].keys()
        assert operation["summary"] and "docs/" in operation["description"]


def test_operations_history_has_formal_cursor_and_global_filters():
    doc=load_openapi("case", "contracts/core")
    operation=doc["paths"]["/api/v1/platform/support-runs"]["get"]
    params={p["name"]:p for p in operation["parameters"]}
    assert {"before","limit","query","status"} <= params.keys()
    page=component_validator("case","SupportOperationsPage","contracts/core")
    assert page.accepts({"items":[],"limit":8,"next_before":None})
    assert not page.accepts({"items":[],"limit":51,"next_before":None})
