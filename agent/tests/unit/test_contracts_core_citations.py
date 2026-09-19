"""Every ``docs/*.md:NN`` citation must point at a real line.

Motivation: ``contracts/core/event-envelope.schema.json`` carried a citation to
``docs/domain-model.md:126`` while that file has 72 lines, and
``contracts/openapi-commerce.yaml`` cited ``docs/product-spec.md:46`` while that file has
40. Nothing failed, because the citation rules covered the OpenAPI documents but not the
JSON Schema files, and they checked that a citation was *written*, not that it pointed
anywhere. A citation that points nowhere is worse than no citation: it reads as evidence
while being unusable.

The scan covers the compat baseline as well as core: both are shipped documents, and the
one wrong citation above lived in the compat file that core was ported from.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT

#: Shipped documents and the contract sources that cite the specs. Tests are excluded:
#: a test that cites a line is describing its own assertion, not shipping a contract.
ROOT_DIRECTORIES = (
    REPO_ROOT / "contracts",
    REPO_ROOT / "agent" / "src" / "resolveflow" / "contracts",
    REPO_ROOT / "java" / "shared-kernel" / "src" / "main" / "java" / "com" / "resolveflow" / "shared" / "contract",
)

SUFFIXES = {".json", ".yaml", ".yml", ".md", ".py", ".java"}

#: ``docs/<name>.md:<line>``; the line number is the whole point, so it is mandatory.
CITATION = re.compile(r"docs/([A-Za-z0-9_.-]+\.md):(\d+)")

CITED_FILES = sorted(
    path for root in ROOT_DIRECTORIES for path in root.rglob("*") if path.is_file() and path.suffix in SUFFIXES
)


def citations_in(path: Path) -> set[tuple[str, int]]:
    return {(match.group(1), int(match.group(2))) for match in CITATION.finditer(path.read_text(encoding="utf-8"))}


def test_the_scan_actually_sees_the_core_documents() -> None:
    """A guard that silently scans nothing would pass forever."""
    assert len(CITED_FILES) >= 8
    found = {name for path in CITED_FILES for name, _ in citations_in(path)}
    assert {"core-contracts.md", "core-scope.md", "domain-model.md"} <= found


@pytest.mark.parametrize("path", CITED_FILES, ids=lambda path: path.name)
def test_every_citation_points_at_an_existing_line(path: Path) -> None:
    cited = citations_in(path)
    if not cited:
        pytest.skip("no citation in this file")
    for name, line in sorted(cited):
        target = REPO_ROOT / "docs" / name
        assert target.is_file(), f"{path.name} cites docs/{name}, which does not exist"
        total = len(target.read_text(encoding="utf-8").splitlines())
        assert line <= total, f"{path.name} cites docs/{name}:{line}, but that file has {total} lines"


def test_no_citation_names_a_line_zero() -> None:
    for path in CITED_FILES:
        for name, line in citations_in(path):
            assert line >= 1, f"{path.name} cites docs/{name}:{line}"