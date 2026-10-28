"""Build the self-hosted display-chain fonts from licensed Noto SC TTF files.

One-off asset tooling: uv run --no-project --with 'fonttools[woff]==4.60.1'
python web/tools/build_display_fonts.py <NotoSansSC-VF.ttf> <NotoSerifSC-VF.ttf>
"""

import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def build(source: Path, target: Path, weights: object) -> dict[str, object]:
    font = TTFont(source)
    source_cmap = set(font.getBestCmap())
    names = {key: font["name"].getDebugName(key) for key in (0, 5, 13, 14)}
    if "SIL Open Font License" not in (names[13] or ""):
        raise RuntimeError(
            "Expected a font distributed under the SIL Open Font License"
        )
    instantiateVariableFont(font, {"wght": weights}, inplace=True)
    font.flavor = "woff2"
    font.save(target)
    rebuilt = TTFont(target)
    if set(rebuilt.getBestCmap()) != source_cmap:
        raise RuntimeError("Font conversion changed Unicode coverage")
    return {
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "output_sha256": sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size,
        "codepoints": len(source_cmap),
        "metadata": names,
    }


def unicode_ranges(points: set[int]) -> str:
    groups: list[tuple[int, int]] = []
    for point in sorted(points):
        if groups and point == groups[-1][1] + 1:
            groups[-1] = (groups[-1][0], point)
        else:
            groups.append((point, point))
    return ",".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in groups)


def split_font(
    source: Path, folder: str, family: str, weights: str, *, reuse: bool = False
) -> tuple[list[dict[str, object]], str]:
    font = TTFont(source)
    coverage = set(font.getBestCmap())
    common = (
        set(range(0x20, 0x100))
        | set(range(0x2000, 0x2070))
        | set(range(0x3000, 0x3040))
    )
    # GB2312 level-one characters and symbols, plus all static UI codepoints.
    for row in [*range(0xA1, 0xAA), *range(0xB0, 0xD8)]:
        for column in range(0xA1, 0xFF):
            common.update(
                map(ord, bytes([row, column]).decode("gb2312", errors="ignore"))
            )
    for path in (source.parents[2] / "src").rglob("*"):
        if path.suffix in {".vue", ".ts", ".css"}:
            common.update(map(ord, path.read_text(encoding="utf-8")))
    common &= coverage
    groups = {"common": common, "extended": coverage - common}
    directory = source.parent / folder
    directory.mkdir(exist_ok=True)
    outputs, rules, verified = [], [], set()
    for name, points in sorted(groups.items()):
        target = directory / f"{name}.woff2"
        if name == "extended":
            # The disjoint unicode-range loads this full-coverage fallback only for
            # uncommon characters; ordinary UI and Chinese text use common.woff2.
            target.write_bytes(source.read_bytes())
        elif not (
            reuse and target.exists() and points <= set(TTFont(target).getBestCmap())
        ):
            part = deepcopy(font)
            options = subset.Options()
            options.layout_features = ["*"]
            options.name_IDs = ["*"]
            options.name_languages = ["*"]
            worker = subset.Subsetter(options=options)
            worker.populate(unicodes=points)
            worker.subset(part)
            part.save(target)
        actual = set(TTFont(target).getBestCmap())
        # Shaping closure can retain additional encoded aliases of required glyphs.
        # Every requested point must survive, and none may be invented outside the source.
        if not points <= actual or not actual <= coverage:
            raise RuntimeError(f"Font subset changed Unicode coverage: {target.name}")
        verified.update(points)
        outputs.append(
            {
                "file": f"{folder}/{name}.woff2",
                "sha256": sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
                "codepoints": len(points),
                "retained_aliases": len(actual - points),
            }
        )
        rules.append(
            f'@font-face {{ font-family: "{family}"; src: url("/fonts/{folder}/{name}.woff2") format("woff2"); font-weight: {weights}; font-style: normal; font-display: swap; unicode-range: {unicode_ranges(points)}; }}'
        )
    if verified != coverage:
        raise RuntimeError("Font subsets lost Unicode coverage")
    return outputs, "\n".join(rules)


if __name__ == "__main__":
    import json

    output = Path(__file__).resolve().parents[2] / "web/public/fonts"
    output.mkdir(parents=True, exist_ok=True)
    results = (
        json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        if sys.argv[1:] == ["--split-existing"]
        else {
            "noto-sans-sc-ui.woff2": build(
                Path(sys.argv[1]), output / "noto-sans-sc-ui.woff2", (400, 400, 600)
            ),
            "noto-serif-sc-reading.woff2": build(
                Path(sys.argv[2]), output / "noto-serif-sc-reading.woff2", 400
            ),
        }
    )
    styles = []
    for filename, folder, family, weights in [
        ("noto-sans-sc-ui.woff2", "sans-sc", "Resolve Sans", "400 600"),
        ("noto-serif-sc-reading.woff2", "serif-sc", "Resolve Reading", "400"),
    ]:
        outputs, css = split_font(
            output / filename,
            folder,
            family,
            weights,
            reuse=sys.argv[1:] == ["--split-existing"],
        )
        results[filename]["subsets"] = outputs
        styles.append(css)
    (output.parents[1] / "src/ui/display-font-faces.css").write_text(
        "/* Generated by web/tools/build_display_fonts.py; do not edit by hand. */\n"
        + "\n".join(styles)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "provenance.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for filename in ("noto-sans-sc-ui.woff2", "noto-serif-sc-reading.woff2"):
        (output / filename).unlink()
    print(
        json.dumps(
            {
                key: {
                    "coverage": value["codepoints"],
                    "files": len(value["subsets"]),
                    "bytes": sum(item["bytes"] for item in value["subsets"]),
                }
                for key, value in results.items()
            }
        )
    )
