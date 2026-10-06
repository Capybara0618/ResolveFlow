"""Offline, source-bound HTML extraction. Never publishes policy or calls a model.

Explicit body selectors describe page layout only. Output is PENDING_REVIEW, not
Java policy rules: headings, tables and exceptions need semantic confirmation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = "policy-html-v1"
MAX_BYTES = 4 * 1024 * 1024
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
SKIP = frozenset("script style noscript nav footer template".split())
LEAF_BLOCKS = frozenset("p li pre blockquote address h1 h2 h3 h4 h5 h6".split())
CONTAINERS = frozenset("div section article main ul ol table tr td th tbody thead tfoot".split())


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_source(source: dict) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(source.get("id", ""))):
        raise ValueError("invalid source id")
    if (
        not str(source.get("subject", "")).startswith("EXTERNAL:")
        or source.get("role") != "EXTERNAL_REFERENCE"
        or source.get("adopted_by_project_merchant") is not False
    ):
        raise ValueError("source must remain an unadopted external reference")
    url = urlparse(source.get("url", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("source URL must be public HTTPS")
    if source.get("encoding") not in {"utf-8", "utf-8-sig", "gb18030"}:
        raise ValueError("explicit supported encoding required")
    selector = source.get("selector")
    if (
        not isinstance(selector, dict)
        or not selector
        or not selector.get("tag")
        or set(selector) - {"tag", "id", "class"}
        or not all(isinstance(value, str) and value for value in selector.values())
    ):
        raise ValueError("explicit tag/id/class selector required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("expected_sha256", ""))):
        raise ValueError("source raw hash required")


def load_sources(directory: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    raw = (directory / "sources.json").read_bytes()
    if manifest.get("files", {}).get("sources.json") != digest(raw):
        raise ValueError("source manifest hash differs")
    sources = json.loads(raw)
    if not isinstance(sources, list) or not sources:
        raise ValueError("empty source manifest")
    for source in sources:
        validate_source(source)
    if (
        len({s["id"] for s in sources}) != len(sources)
        or len({s["url"] for s in sources}) != len(sources)
        or manifest.get("documents") != len(sources)
        or manifest.get("source_families") != len({s["subject"] for s in sources})
    ):
        raise ValueError("source manifest identity/count differs")
    return sources


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None]
    start: int
    end: int
    line: int
    column: int
    path: str
    children: list[Node | str] = field(default_factory=list)


class Tree(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", html)]
        self.root = Node("document", {}, 0, len(html), 1, 0, "/document")
        self.stack = [self.root]
        self.warnings: set[str] = set()
        self.feed(html)
        self.close()
        if len(self.stack) > 1:
            self.warnings.add("UNCLOSED_HTML")
            for node in self.stack[1:]:
                node.end = len(html)

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.source_offset()
        # HTML permits omitted end tags. Record recovery instead of silently
        # merging neighboring list items/cells into a single rule.
        boundary = {"li": {"ul", "ol"}, "td": {"tr"}, "th": {"tr"}, "tr": {"table"}, "p": {"div", "article"}}
        if tag in boundary:
            for index in range(len(self.stack) - 1, 0, -1):
                previous = self.stack[index]
                if previous.tag == tag or (tag in {"td", "th"} and previous.tag in {"td", "th"}):
                    self.warnings.add("IMPLICIT_HTML_CLOSE")
                    for node in self.stack[index:]:
                        node.end = start
                    del self.stack[index:]
                    break
                if previous.tag in boundary[tag]:
                    break
        parent = self.stack[-1]
        number = sum(isinstance(c, Node) and c.tag == tag for c in parent.children) + 1
        line, column = self.getpos()
        node = Node(
            tag,
            dict(attrs),
            start,
            start + len(self.get_starttag_text()),
            line,
            column,
            f"{parent.path}/{tag}[{number}]",
        )
        parent.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        start = self.source_offset()
        end = self.html.find(">", start) + 1
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                if index != len(self.stack) - 1:
                    self.warnings.add("IMPLICIT_HTML_CLOSE")
                for node in self.stack[index:]:
                    node.end = end
                del self.stack[index:]
                return
        if tag not in VOID:
            self.warnings.add("UNMATCHED_HTML_CLOSE")

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def visible(node: Node) -> bool:
    style = re.sub(r"\s", "", node.attrs.get("style") or "").lower()
    return (
        node.tag not in SKIP
        and "hidden" not in node.attrs
        and node.attrs.get("aria-hidden") != "true"
        and "display:none" not in style
        and "visibility:hidden" not in style
    )


def text_of(node: Node) -> str:
    if not visible(node):
        return ""
    if node.tag == "br":
        return "\n"
    return "".join(child if isinstance(child, str) else text_of(child) for child in node.children)


def clean(text: str) -> str:
    return "\n".join(part for line in text.splitlines() if (part := re.sub(r"\s+", " ", line).strip()))


def descendants(node: Node):
    if not visible(node):
        return
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from descendants(child)


def locator(node: Node) -> dict:
    return {"path": node.path, "line": node.line, "column": node.column, "start_char": node.start, "end_char": node.end}


def parse_document(raw: bytes, source: dict) -> dict:
    validate_source(source)
    if len(raw) > MAX_BYTES:
        raise ValueError("snapshot too large")
    if digest(raw) != source["expected_sha256"]:
        raise ValueError(f"snapshot hash differs for {source['id']}")
    try:
        html = raw.decode(source["encoding"], errors="strict")
    except UnicodeDecodeError as failure:
        raise ValueError("snapshot encoding differs") from failure
    if "\ufffd" in html:
        raise ValueError("snapshot encoding contains replacement characters")
    tree = Tree(html)
    selector = source["selector"]
    roots = [
        node
        for node in descendants(tree.root)
        if node.tag == selector["tag"]
        and all(
            value in (node.attrs.get("class") or "").split() if key == "class" else node.attrs.get(key) == value
            for key, value in selector.items()
            if key != "tag"
        )
    ]
    if len(roots) != 1:
        raise ValueError("body selector must match exactly one visible element")
    warnings = tree.warnings
    blocks = []
    headings: list[tuple[int, str]] = []

    def add(node, kind, text, **extra):
        text = clean(text)
        if not text:
            return
        inline_titles = [
            n
            for n in descendants(node)
            if n.tag in {"strong", "b"} or re.search(r"font-weight\s*:\s*(?:bold|[6-9]00)", n.attrs.get("style") or "")
        ]
        inline_heading = kind == "paragraph" and any(clean(text_of(n)) == text for n in inline_titles)
        if inline_heading:
            warnings.add("INLINE_HEADING_CANDIDATE_REQUIRES_REVIEW")
        blocks.append(
            {
                "id": f"{source['id']}:b{len(blocks) + 1:04d}",
                "kind": kind,
                "section_path": [title for _, title in headings],
                "text": text,
                "text_sha256": digest(text.encode()),
                "locator": locator(node),
                "raw_fragment_sha256": digest(html[node.start : node.end].encode("utf-8")),
                "inline_heading_candidate": inline_heading,
                **extra,
            }
        )

    def span(cell, key):
        value = cell.attrs.get(key) or "1"
        if not value.isdecimal() or not 1 <= int(value) <= 1024:
            warnings.add("INVALID_TABLE_SPAN")
            return None
        if int(value) > 1:
            warnings.add("TABLE_SPANS_REQUIRE_REVIEW")
        return int(value)

    def table(node):
        # Preserve cells as a grid description, including raw span attributes.
        # Do not pretend complex merged headers have been semantically resolved.
        if any(n.tag == "table" and n is not node for n in descendants(node)):
            warnings.add("NESTED_TABLE_REQUIRES_REVIEW")
        rows = []
        for row in (n for n in descendants(node) if n.tag == "tr"):
            cells = [c for c in row.children if isinstance(c, Node) and c.tag in {"td", "th"} and visible(c)]
            if cells:
                rows.append(
                    [
                        {
                            "text": clean(text_of(c)),
                            "header": c.tag == "th",
                            "column": col,
                            "rowspan": span(c, "rowspan"),
                            "colspan": span(c, "colspan"),
                            "locator": locator(c),
                        }
                        for col, c in enumerate(cells)
                    ]
                )
        if not rows:
            warnings.add("EMPTY_TABLE")
        elif not any(c["header"] for row in rows for c in row):
            warnings.add("TABLE_HEADER_REQUIRES_REVIEW")
        add(node, "table", "\n".join(" | ".join(c["text"] for c in row) for row in rows), rows=rows)

    def walk(node, depth=0):
        if not visible(node):
            return
        if node.tag == "table":
            table(node)
            return
        if node.tag in {"ul", "ol"}:
            depth += 1
        if re.fullmatch(r"h[1-6]", node.tag):
            level = int(node.tag[1])
            title = clean(text_of(node))
            if title:
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                add(node, "heading", title, heading_level=level)
            return
        pieces = []

        def flush():
            add(
                node,
                "list_item" if node.tag == "li" else "paragraph",
                "".join(pieces),
                **({"list_depth": depth} if node.tag == "li" else {}),
            )
            pieces.clear()

        for child in node.children:
            if isinstance(child, str):
                pieces.append(child)
            elif child.tag in LEAF_BLOCKS | CONTAINERS:
                flush()
                walk(child, depth)
            else:
                pieces.append(text_of(child))
        flush()

    walk(roots[0])
    if not blocks:
        raise ValueError("empty extracted body; dynamic pages are not supported")
    if not any(b["kind"] == "heading" for b in blocks):
        warnings.add("NO_SEMANTIC_HEADINGS_REQUIRES_REVIEW")
    return {
        "source_id": source["id"],
        "subject": source["subject"],
        "source_url": source["url"],
        "raw_sha256": digest(raw),
        "encoding": source["encoding"],
        "selector": selector,
        "parser_version": VERSION,
        "status": "PENDING_REVIEW",
        "indexable": False,
        "warnings": sorted(warnings),
        "blocks": blocks,
    }


def parse_snapshot(sources: list[dict], cache: Path) -> dict:
    if not sources:
        raise ValueError("empty source snapshot")
    for source in sources:
        validate_source(source)
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("duplicate snapshot source ids")
    documents = [parse_document((cache / f"{s['id']}.html").read_bytes(), s) for s in sources]
    return {
        "parser_version": VERSION,
        "parser_sha256": digest(Path(__file__).read_bytes()),
        "source_config_sha256": digest(json.dumps(sources, ensure_ascii=False, sort_keys=True).encode()),
        "documents": documents,
        "independent_gold_count": 0,
        "indexable_documents": 0,
        "status": "PENDING_REVIEW",
    }


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlparse(req.full_url), urlparse(newurl)
        if new.scheme != "https" or new.hostname != old.hostname or new.username or new.password:
            raise ValueError("cross-host or non-HTTPS redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_snapshots(sources: list[dict], cache: Path) -> None:
    """Explicit network mode. Freeze bytes, never overwrite a cache or accept drift."""
    if cache.exists():
        raise FileExistsError("use a new cache directory; existing snapshots are immutable")
    captures = []
    opener = build_opener(SameHostRedirect())
    for source in sources:
        validate_source(source)
        # validate_source and SameHostRedirect restrict both initial and redirected requests to HTTPS.
        request = Request(source["url"], headers={"User-Agent": "ResolveFlow-policy-research/1.0"})  # noqa: S310
        with opener.open(request, timeout=25) as response:
            if response.status != 200 or response.headers.get_content_type() != "text/html":
                raise ValueError("source is not HTTP200 HTML")
            raw = response.read(MAX_BYTES + 1)
            # Parse now as well: an anti-bot/login page is not a policy snapshot.
            parse_document(raw, source)
            captures.append(
                (
                    source,
                    raw,
                    {
                        "url": source["url"],
                        "final_url": response.url,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "sha256": digest(raw),
                        "bytes": len(raw),
                        "content_type": response.headers.get("Content-Type"),
                    },
                )
            )
    cache.mkdir(parents=True)
    for source, raw, capture in captures:
        (cache / f"{source['id']}.html").write_bytes(raw)
        (cache / f"{source['id']}.capture.json").write_text(
            json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evals/policy-documents-v1"))
    parser.add_argument("--cache", type=Path, default=Path("tmp/policy-documents-v1"))
    parser.add_argument("--output", type=Path, required=True, help="new local JSON output; refuses overwrite")
    parser.add_argument("--fetch", action="store_true", help="explicit HTTPS fetch into a new cache directory")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("existing output must not be overwritten")
    sources = load_sources(args.dataset)
    if args.fetch:
        fetch_snapshots(sources, args.cache)
    report = parse_snapshot(sources, args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(
        json.dumps(
            {
                "documents": len(report["documents"]),
                "indexable_documents": 0,
                "status": report["status"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
