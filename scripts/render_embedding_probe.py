"""Render the C07.1 embedding probe into the report a reader checks (``reports/c071-policy-index/``).

The probe itself is a throwaway in ``tmp/`` (gitignored, with its own venv): it downloaded the candidate model and
measured it *before* any of it was written into ``pyproject.toml`` or into ``EMBEDDING_MODEL``. What has to survive
is the **result**, because ``docs/policy-rag.md:19`` asks for the model's revision, dimension, licence and cost to
be fixed and recorded — and "recorded" means a file in the repository, not a terminal scrollback.

``tmp/c071-probe/probe-embedding-result.json`` is the probe's raw output; this renders it. Run after the probe::

    & tmp\\c071-probe\\.venv\\Scripts\\python.exe tmp\\c071-probe\\probe_embedding.py
    & agent\\.venv\\Scripts\\python.exe scripts\\render_embedding_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "tmp" / "c071-probe" / "probe-embedding-result.json"
TARGET = REPO_ROOT / "reports" / "c071-policy-index" / "embedding-probe.txt"


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"{SOURCE} is missing; run tmp/c071-probe/probe_embedding.py first")
    document = json.loads(SOURCE.read_text(encoding="utf-8"))

    lines = [
        "C07.1 embedding probe (measured before the model was written into the code)",
        "",
        "Why this file exists: docs/policy-rag.md:19 requires the embedding model's revision, dimension, licence",
        "and resource cost to be fixed and recorded, and docs/policy-rag.md:19 forbids faking an embedding. So the",
        "candidate was downloaded and measured on this machine first, and the numbers below are what the probe",
        "printed — including the query it gets wrong. The probe's own source and its venv live in tmp/ (gitignored,",
        "one-off); the result is here because a measurement nobody can read is not a record.",
        "",
        f"corpus segments probed : {document['corpus_size']}",
        f"queries probed         : {document['queries']}",
        "",
    ]

    for entry in document["models"]:
        lines.extend(
            [
                f"model            : {entry['model']}",
                f"revision (pinned) : {entry['revision']}",
                f"licence           : {entry['license']}",
                f"dimension         : {entry['dimension']}",
                f"files in snapshot : {entry['siblings']}",
                f"weights on disk   : {entry['weights_bytes'] / 1_000_000:.1f} MB",
                f"download          : {entry['download_seconds']}s (one HTTPS read timeout, resumed)",
                f"load              : {entry['load_seconds']}s",
                f"encode corpus     : {entry['encode_corpus_seconds']}s",
                f"encode queries    : {entry['encode_queries_seconds']}s",
                f"distinct vectors  : {entry['distinct_rule_vectors']} of {document['corpus_size']} segments",
                f"top-1 on probe    : {entry['top1_correct']}/{entry['top1_total']}",
                "",
                "per query (cosine, all corpus segments):",
            ]
        )
        for ranking in entry["rankings"]:
            mark = "ok  " if ranking["ok"] else "MISS"
            lines.append(f"  {mark} {ranking['query']}")
            lines.append(f"       expected {ranking['expected']}, top-1 {ranking['top1']}")
            for scored in ranking["scores"]:
                lines.append(f"         {scored['cosine']:>7.4f}  {scored['rule_id']}")
            lines.append("")

    lines.extend(
        [
            "reading this probe:",
            "  * The one MISS is kept, not tuned away. A model chosen because it scored well on the queries that",
            "    survived is a model chosen by its own test set; the miss is recorded so a later reader knows what",
            "    this model does not separate well (a lost-parcel question whose phrasing leans on 签收).",
            "  * Pairwise ordering is what matters here, not the absolute cosine values: the probe asked whether the",
            "    correct rule outranks the others, which is the property retrieval depends on.",
            "  * The cosine spread on this corpus is narrow (roughly 0.31-0.72), which is why the evaluation reports",
            "    top-1 and MRR@5 rather than assuming a wide margin separates the rules.",
            "  * Dependency cost, measured separately in a throwaway venv: 811 MB of site-packages, 474 MB of which",
            "    is torch, plus the weights above. That is the real number behind the `retrieval` extra.",
            "  * This machine cannot create the symlinks huggingface_hub uses for its cache layout (WinError 1314),",
            "    so the snapshot is downloaded to a plain directory; that is a filesystem fact, not a model problem.",
        ]
    )

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
