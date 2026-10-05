from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.evaluation.dataset import read  # noqa: E402
from scripts.evaluation.harness_checks import context_check, harness_check  # noqa: E402


@pytest.mark.parametrize("name", [item["id"] for item in read("harness/checks.json")])
def test_current_harness_invariant(name):
    assert harness_check(name)["passed"]


@pytest.mark.parametrize("name", [item["id"] for item in read("harness/context.json")])
def test_current_context_invariant(name):
    assert context_check(name)["passed"]
