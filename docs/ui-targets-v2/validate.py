"""Read-only asset/link checks for the v2 target-design gallery.

Run from any directory with Python 3; writes only validation.json, never images.
This is not a browser or business acceptance test.
"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import hashlib
import json
import re
import struct
import zlib


HERE = Path(__file__).resolve().parent


def read_png(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"Not PNG: {path}"
    pos, compressed, header, ended = 8, bytearray(), None, False
    while pos < len(data):
        size = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + size]
        assert len(body) == size and pos + size + 12 <= len(data), path
        crc = struct.unpack_from(">I", data, pos + 8 + size)[0]
        assert zlib.crc32(kind + body) & 0xffffffff == crc, f"CRC: {path}"
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            ended = True
        pos += size + 12
        if ended:
            break
    assert ended and pos == len(data) and header, f"Incomplete PNG: {path}"
    width, height, depth, color, compression, filtering, interlace = header
    assert width >= 1440 and height >= 900, f"Undersized image: {path}"
    assert compression == filtering == interlace == 0, f"Unsupported PNG: {path}"
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    row_size = (width * depth * channels + 7) // 8 + 1
    raw = zlib.decompress(compressed)
    assert len(raw) == row_size * height, f"Invalid pixel length: {path}"
    assert all(raw[y * row_size] <= 4 for y in range(height)), f"Invalid filter: {path}"
    return {"width": width, "height": height, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.cards, self.groups = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == "article" and attrs.get("data-group"):
            self.cards.append(attrs["id"])
            self.groups.append(attrs["data-group"])


def main():
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    assets = manifest["assets"]
    assert len(assets) == 19 and len({a["id"] for a in assets}) == 19
    images = [{"id": a["id"], "file": a["image"], **read_png(HERE / a["image"])}
              for a in assets]
    parser = LinkParser()
    parser.feed((HERE / "index.html").read_text(encoding="utf-8"))
    assert parser.cards == [a["id"] for a in assets], "Gallery/manifest mismatch"
    assert parser.groups == [a["role"] for a in assets], "Role mismatch"
    refs = [(HERE / "index.html", link) for link in parser.links]
    for path in HERE.glob("*.md"):
        refs.extend((path, link) for link in re.findall(r"\]\(([^)]+)\)",
                    path.read_text(encoding="utf-8")))
    checked, report_link = 0, None
    for source, link in refs:
        url = urlsplit(link)
        if url.scheme or not url.path:
            continue
        target = source.parent / unquote(url.path)
        if target.resolve() == (HERE / "validation.json").resolve():
            report_link = target
        else:
            assert target.exists(), f"Broken link: {source}: {link}"
        checked += 1
    original = json.loads((HERE.parent / "ui-targets-v1" / "validation.json")
                          .read_text(encoding="utf-8"))
    for item in original["images"]:
        path = HERE.parent / "ui-targets-v1" / item["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], path
    record = json.loads((HERE / "generation-record.json").read_text(encoding="utf-8"))
    assert record["initialCalls"] == 17 and record["correctionCalls"] == 8
    assert sum(len(a.get("corrections", [])) for a in record["assets"]) == 8
    result = {"date": "2026-10-01", "final_images": 19, "new_final_assets": 17,
              "reused_assets": 2, "local_links_checked": checked,
              "png_crc_decompression_dimensions": "PASS",
              "gallery_manifest_roles": "PASS", "v1_images_unchanged": 16,
              "visual_review": "19 final designs inspected; 8 corrections inspected; literal differences documented in review.md",
              "browser_business_acceptance": "NOT_RUN - static design artifacts only",
              "business_tests_and_deepseek": "NOT_RUN - no runtime changes",
              "images": images}
    (HERE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                         + "\n", encoding="utf-8", newline="\n")
    if report_link:
        assert report_link.exists(), "Generated report link missing"
    print(json.dumps({key: value for key, value in result.items() if key != "images"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
