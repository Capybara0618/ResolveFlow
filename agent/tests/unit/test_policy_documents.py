"""Generic document structure/provenance failures, independent of refund decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.policy_documents import SameHostRedirect, load_sources, parse_document, parse_snapshot


def source(raw: bytes, **updates):
    value = {
        "id": "sample",
        "subject": "EXTERNAL:SAMPLE",
        "url": "https://example.org/policy",
        "role": "EXTERNAL_REFERENCE",
        "adopted_by_project_merchant": False,
        "encoding": "utf-8",
        "selector": {"tag": "article", "id": "policy"},
        "expected_sha256": hashlib.sha256(raw).hexdigest(),
    }
    return value | updates


def test_sections_exceptions_and_original_locations_are_kept():
    html = (
        '<nav>广告</nav>\n<article id="policy"><h2>条件</h2><p>允许退货。</p>\n'
        "<h3>例外</h3><p>定制品除外。</p></article>"
    )
    raw = html.encode()
    report = parse_document(raw, source(raw))
    assert report["status"] == "PENDING_REVIEW" and report["indexable"] is False
    blocks = report["blocks"]
    assert [b["text"] for b in blocks] == ["条件", "允许退货。", "例外", "定制品除外。"]
    assert blocks[-1]["section_path"] == ["条件", "例外"]
    for block in blocks:
        loc = block["locator"]
        assert loc["line"] > 0 and loc["start_char"] < loc["end_char"] <= len(html)
        assert html[loc["start_char"] : loc["end_char"]].startswith("<")
        assert (
            block["raw_fragment_sha256"]
            == hashlib.sha256(html[loc["start_char"] : loc["end_char"]].encode()).hexdigest()
        )
        assert block["text_sha256"] == hashlib.sha256(block["text"].encode()).hexdigest()


def test_table_retains_header_cell_relationship_not_flat_text():
    raw = (
        b'<article id="policy"><table><tr><th>Reason</th><th>Fee</th></tr>'
        b"<tr><td>Damage</td><td>No</td></tr></table></article>"
    )
    block = parse_document(raw, source(raw))["blocks"][0]
    assert block["kind"] == "table"
    assert block["rows"][0][0]["header"] is True
    assert [c["text"] for c in block["rows"][1]] == ["Damage", "No"]
    assert block["rows"][1][1]["column"] == 1


def test_spanning_table_is_preserved_but_needs_review():
    raw = b'<article id="policy"><table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table></article>'
    report = parse_document(raw, source(raw))
    assert "TABLE_SPANS_REQUIRE_REVIEW" in report["warnings"]
    assert report["blocks"][0]["rows"][0][0]["rowspan"] == 2
    assert report["indexable"] is False


def test_nested_lists_do_not_repeat_child_text_and_preserve_depth():
    raw = '<article id="policy"><ul><li>限制<ul><li>例外一</li></ul></li></ul></article>'.encode()
    blocks = parse_document(raw, source(raw))["blocks"]
    assert [b["text"] for b in blocks] == ["限制", "例外一"]
    assert [b["list_depth"] for b in blocks] == [1, 2]


def test_scripts_hidden_text_and_footer_do_not_become_policy():
    raw = (
        b'<article id="policy"><script>approve()</script><p hidden>hidden</p>'
        b'<p style="display: none">secret</p><footer>noise</footer><p>visible<br>line</p></article>'
    )
    assert parse_document(raw, source(raw))["blocks"][0]["text"] == "visible\nline"


@pytest.mark.parametrize(
    "html", ["<article>text</article>", '<article id="policy">A</article><article id="policy">B</article>']
)
def test_missing_or_ambiguous_body_selector_fails(html):
    raw = html.encode()
    with pytest.raises(ValueError, match="exactly one"):
        parse_document(raw, source(raw))


def test_changed_snapshot_cannot_reuse_old_source_hash():
    raw = b'<article id="policy">A</article>'
    with pytest.raises(ValueError, match="hash"):
        parse_document(raw + b" ", source(raw))


def test_gbk_is_strictly_decoded_without_replacement():
    raw = '<article id="policy"><p>条件和例外</p></article>'.encode("gb18030")
    assert parse_document(raw, source(raw, encoding="gb18030"))["blocks"][0]["text"] == "条件和例外"
    with pytest.raises(ValueError, match="encoding"):
        parse_document(raw, source(raw))


def test_script_only_body_is_not_successful_extraction():
    raw = b'<article id="policy"><script>render()</script></article>'
    with pytest.raises(ValueError, match="empty"):
        parse_document(raw, source(raw))


def test_optional_html_closing_tags_are_explicitly_recorded():
    raw = b'<article id="policy"><ul><li>A<li>B</ul></article>'
    report = parse_document(raw, source(raw))
    assert [b["text"] for b in report["blocks"]] == ["A", "B"]
    assert "IMPLICIT_HTML_CLOSE" in report["warnings"]


@pytest.mark.parametrize(
    "updates",
    [
        {"id": "../escape"},
        {"subject": "M-1001"},
        {"adopted_by_project_merchant": True},
        {"selector": {}},
        {"selector": {"tag": "article", "unsupported": "x"}},
        {"url": "file:///tmp/document"},
        {"encoding": "guess"},
    ],
)
def test_invalid_reference_or_selector_is_refused(updates):
    raw = b'<article id="policy">A</article>'
    with pytest.raises(ValueError):
        parse_document(raw, source(raw, **updates))


def test_manifest_tampering_is_refused(tmp_path):
    src = tmp_path / "sources.json"
    src.write_text("[]", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"sources.json": "0" * 64}}), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        load_sources(tmp_path)


def test_snapshot_missing_file_fails_without_creating_output(tmp_path):
    raw = b'<article id="policy">A</article>'
    with pytest.raises(FileNotFoundError):
        parse_snapshot([source(raw)], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_eof_unclosed_structure_is_visible_to_reviewer():
    raw = b'<article id="policy"><p>A'
    assert "UNCLOSED_HTML" in parse_document(raw, source(raw))["warnings"]


def test_oversized_snapshot_is_refused():
    raw = b"x" * (4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="large"):
        parse_document(raw, source(raw))


def test_empty_manifest_is_refused(tmp_path: Path):
    data = b"[]"
    (tmp_path / "sources.json").write_bytes(data)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"files": {"sources.json": hashlib.sha256(data).hexdigest()}, "documents": 0, "source_families": 0}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="empty"):
        load_sources(tmp_path)


def test_inline_bold_title_is_flagged_without_inventing_section_structure():
    raw = b'<article id="policy"><h1>Policy</h1><p><strong>Exceptions</strong></p><p>Terms</p></article>'
    report = parse_document(raw, source(raw))
    assert "INLINE_HEADING_CANDIDATE_REQUIRES_REVIEW" in report["warnings"]
    assert report["blocks"][1]["inline_heading_candidate"] is True
    assert report["blocks"][-1]["section_path"] == ["Policy"]


def test_table_without_explicit_headers_requires_review():
    raw = b'<article id="policy"><table><tr><td>Reason</td><td>Fee</td></tr></table></article>'
    assert "TABLE_HEADER_REQUIRES_REVIEW" in parse_document(raw, source(raw))["warnings"]


def test_traversal_is_refused_before_reading_a_snapshot(tmp_path):
    raw = b'<article id="policy">A</article>'
    with pytest.raises(ValueError, match="source id"):
        parse_snapshot([source(raw, id="../escape")], tmp_path)


@pytest.mark.parametrize("url", ["http://example.org/login", "https://other.example/policy", "file:///tmp/policy"])
def test_fetch_redirect_cannot_escape_source_host(url):
    from urllib.request import Request

    request = Request("https://example.org/policy")
    with pytest.raises(ValueError, match="redirect"):
        SameHostRedirect().redirect_request(request, None, 302, "redirect", {}, url)


def test_existing_snapshot_cache_is_not_overwritten(tmp_path):
    from scripts.policy_documents import fetch_snapshots

    with pytest.raises(FileExistsError, match="immutable"):
        fetch_snapshots([], tmp_path)


def test_duplicate_snapshot_sources_are_refused_before_read(tmp_path):
    raw = b'<article id="policy">A</article>'
    with pytest.raises(ValueError, match="duplicate"):
        parse_snapshot([source(raw), source(raw)], tmp_path)


def test_unknown_encoding_cannot_silently_drop_bytes():
    raw = b'<article id="policy">\xff</article>'
    with pytest.raises(ValueError, match="encoding"):
        parse_document(raw, source(raw))
