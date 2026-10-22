import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator


@pytest.mark.parametrize("owner", ["case", "commerce"])
def test_review_fixtures_and_strict_public_write_contract(owner):
    fixtures = json.loads((REPO_ROOT / "contracts/core/fixtures/product-reviews.json").read_text(encoding="utf-8"))
    for name, body in fixtures.items():
        validator = component_validator(owner, name, "contracts/core").validator
        assert not list(validator.iter_errors(body)), name
        assert list(validator.iter_errors({**body, "customer_secret": "forbidden"})), name
    write = component_validator(owner, "ProductReviewWrite", "contracts/core").validator
    for field, value in [
        ("rating", 6), ("rating", "5"), ("rating", 4.5), ("body", " "), ("body", 5),
        ("expected_version", -1), ("expected_version", "0"),
    ]:
        bad = {**fixtures["ProductReviewWrite"], field: value}
        assert list(write.iter_errors(bad)), bad
    public = component_validator(owner, "ProductReviewPage", "contracts/core").validator
    leaked = copy.deepcopy(fixtures["ProductReviewPage"])
    leaked["items"][0]["line_id"] = "private"
    assert list(public.iter_errors(leaked))
