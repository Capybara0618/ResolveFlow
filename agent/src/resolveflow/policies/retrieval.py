"""The two retrieval paths: real dense embeddings, and BM25 as the offline baseline (C07.1).

``docs/policy-rag.md:17`` fixes what each is *for*: dense cosine is the online path, and **BM25 is an
offline baseline rather than a second online recall route**. They live in one module because they rank the
same candidates and their disagreement is the measurement, but nothing here combines them — hybrid, RRF and
rerank are explicitly out of scope (``docs/policy-rag.md:17``), and a module that had a fusion function would
be an invitation to add one "just for the report".

**Dense: the measured choice, not the default one.** The corpus is Chinese, so the library's English default
model is not a candidate. ``BAAI/bge-small-zh-v1.5`` was measured on this machine before it was written into
``pyproject.toml``; the numbers, including the query it gets wrong, are in
``reports/c071-policy-index/`` and repeated in :data:`EMBEDDING_MODEL`'s comment. The revision is pinned to a
commit rather than a branch: a mutable ``main`` would make two runs of the same evaluation incomparable,
which is the whole reason ``docs/policy-rag.md:19`` asks for a fixed revision.

**Why the model is loaded lazily.** Importing ``sentence_transformers`` costs about a second and 200 MB of
resident memory, and most of the suite — every test that does not retrieve — has no use for either. The
import happens inside :func:`embedder`, so the BM25 path and the whole non-retrieval suite never pay it.

**Why a missing stack is an error and not a fallback.** If ``sentence_transformers`` is absent, the dense path
raises :class:`EmbeddingUnavailableError` naming what is missing. It does **not** silently return BM25
results: that would be the "second, degraded search path" ``docs/policy-rag.md:23`` forbids, and it would make
a report say "dense scored 0.6" about a run that never embedded anything.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Final, Protocol

__all__ = [
    "BM25_BASELINE_NOTE",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_LICENSE",
    "EMBEDDING_MODEL",
    "EMBEDDING_REVISION",
    "Embedder",
    "EmbeddingUnavailableError",
    "SentenceTransformerEmbedder",
    "bm25_scores",
    "cosine_similarity",
    "embedder",
    "tokenize",
]

#: ``docs/policy-rag.md:19``: 实测可用模型并固定 revision/维度/许可与资源开销.
#:
#: Measured on this machine (2026-09-25, ``reports/c071-policy-index/embedding-probe.txt``), before this
#: constant existed: 512 dimensions, MIT licence, 192 MB of weights, ~0.2 s to load from a local snapshot,
#: 0.05 s to encode the 22-segment corpus, 0.01 s for the eight probe queries, and 7/8 top-1 on policy
#: wording — the miss is recorded rather than tuned away, because a model chosen because it scored well on
#: the queries that were kept is a model chosen by its own test set.
EMBEDDING_MODEL: Final = "BAAI/bge-small-zh-v1.5"
EMBEDDING_REVISION: Final = "7999e1d3359715c523056ef9478215996d62a620"
EMBEDDING_DIMENSION: Final = 512
EMBEDDING_LICENSE: Final = "MIT"

#: The reason this module has a lexical path at all. Quoted in the report so the number BM25 produces is not
#: read as a proposal for a second online route.
BM25_BASELINE_NOTE: Final = (
    "BM25 is an offline baseline for comparison (docs/policy-rag.md:17), not a second online recall route "
    "and not a fallback for dense: hybrid/RRF/rerank are out of scope."
)


class EmbeddingUnavailableError(RuntimeError):
    """The dense stack is not installed, so no embedding can be produced.

    Raised rather than absorbed. ``docs/policy-rag.md:23`` forbids a degraded "search succeeded anyway" path,
    and the honest report of a missing dependency is a named failure.
    """


class Embedder(Protocol):
    """Turns text into unit vectors. A Protocol so the index can be tested without 200 MB of torch."""

    @property
    def model(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class SentenceTransformerEmbedder:
    """The measured Chinese embedding model, loaded from a local snapshot.

    ``local_path`` is where the snapshot was downloaded. It is required rather than a bare model id because
    this machine cannot create the symlinks ``huggingface_hub`` uses for its cache layout (measured: WinError
    1314 while the weights themselves downloaded fine), and a plain directory sidesteps that without
    pretending the failure was something else.
    """

    local_path: str
    _model: Any = None

    @property
    def model(self) -> str:
        return EMBEDDING_MODEL

    @property
    def revision(self) -> str:
        return EMBEDDING_REVISION

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION

    def _encoder(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as missing:  # pragma: no cover - depends on the machine
                raise EmbeddingUnavailableError(
                    "the dense retrieval stack is not installed: `sentence-transformers` is missing. "
                    "Install the `retrieval` extra (`uv sync --project agent --extra retrieval`); this path "
                    "has no fallback on purpose (docs/policy-rag.md:23)."
                ) from missing
            # `dataclass(frozen=True)` forbids assigning here, so the cache lives in a mutable slot the
            # frozen wrapper does not see. Kept small deliberately: one loaded model per process.
            object.__setattr__(self, "_model", SentenceTransformer(self.local_path))
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Unit vectors, so a dot product is the cosine and no caller has to remember to normalise."""
        if not texts:
            return []
        encoder = self._encoder()
        from resolveflow.policies.segments import encoder_tokens

        if any(encoder_tokens(text, encoder.tokenizer) > encoder.max_seq_length for text in texts):
            raise ValueError("embedding input exceeds encoder window; split policies or shorten query, no truncation")
        vectors = encoder.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]

    def policy_segments(self, text: str) -> list[dict[str, Any]]:
        from resolveflow.policies.segments import TARGET_ENCODER_TOKENS, split_for_encoder

        encoder = self._encoder()
        return split_for_encoder(
            text, encoder.tokenizer, min(TARGET_ENCODER_TOKENS, encoder.max_seq_length), encoder.max_seq_length
        )


def embedder(local_path: str | None = None) -> Embedder:
    """The dense embedder for this project, from an environment override or the default snapshot path.

    The override exists for a deployment that keeps its model somewhere else; there is no override for the
    *model*, because ``docs/policy-rag.md:19`` fixes it and a swappable model would make the recorded
    revision a decoration.
    """
    import os

    path = local_path or os.environ.get("RESOLVEFLOW_EMBEDDING_PATH") or _default_snapshot()
    return SentenceTransformerEmbedder(local_path=path)


def _default_snapshot() -> str:
    """Where the ingestion script puts the pinned snapshot, relative to the repository root."""
    from resolveflow.contracts._schemaio import REPO_ROOT

    return str(REPO_ROOT / "tmp" / "c071-probe" / "models" / EMBEDDING_MODEL.replace("/", "--"))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two vectors, tolerant of vectors that were stored without normalisation.

    Normalised on both sides rather than assuming the caller normalised: vectors read back from the database
    arrive as plain ``real[]``, and a stored vector that lost its normalisation would otherwise make the
    ranking depend on magnitude.
    """
    if len(left) != len(right):
        raise ValueError(f"cannot compare a {len(left)}-dimensional vector with a {len(right)}-dimensional one")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


#: Characters that carry no retrieval signal in this corpus and would otherwise become BM25 terms. Punctuation
#: and whitespace only: dropping numbers or units would erase ``7 天`` / ``48 小时``, which are exactly the
#: thresholds a policy query is about.
_PUNCTUATION = re.compile(r"[\s，。；：！？、（）「」『』【】《》…—·,.;:!?()\[\]{}<>\"'`~@#$%^&*+=|\\/-]+")


def tokenize(text: str) -> list[str]:
    """Chinese-aware tokens for BM25, via jieba.

    jieba rather than character bigrams because the queries and the rules are both short and the terms that
    matter are words (``签收``, ``丢失``, ``退款``): a bigram index would match ``签收`` inside ``未签收`` as
    readily as on its own, which is the opposite of what a policy query needs.

    A missing jieba is not fatal here, unlike the dense stack: the lexical baseline falls back to
    punctuation-split text so a BM25 number can still be produced on a machine without the extra. The result
    says which tokeniser produced it, because the two are not the same measurement.

    The ``import-untyped`` ignore is inline rather than a ``pyproject.toml`` override, and that is deliberate:
    ``scripts/verify.ps1`` runs ``mypy agent/src`` from the **repository root**, where ``agent/pyproject.toml`` is
    not loaded, so a config-only ignore does not apply to the gate. Installing the extra made the gate *more*
    capable — it went from "module not installed" (silent) to "installed, no stubs" (reported) — and this inline
    form is the one that holds wherever the checker is run from.
    """
    cleaned = _PUNCTUATION.sub(" ", text)
    try:
        import jieba  # type: ignore[import-untyped]  # no stubs published; see this docstring
    except ImportError:  # pragma: no cover - depends on the machine
        return [piece for piece in cleaned.split() if piece]
    return [piece.strip() for piece in jieba.lcut(cleaned) if piece.strip()]


def bm25_scores(documents: list[str], query: str) -> list[float]:
    """BM25 scores of ``documents`` for ``query``, in document order.

    ``rank_bm25`` when it is installed, and a self-contained implementation otherwise, so the baseline can be
    reproduced on a machine that only has the repository. Both are BM25 with the usual ``k1=1.5``/``b=0.75``;
    the fallback is here rather than in a test helper because a number in ``reports/`` has to be reproducible
    by whoever reads it.
    """
    if not documents:
        return []
    tokenized = [tokenize(document) for document in documents]
    query_terms = tokenize(query)
    if not query_terms:
        return [0.0] * len(documents)
    try:
        from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]  # no stubs; see bm25_scores
    except ImportError:  # pragma: no cover - depends on the machine
        return _bm25_okapi(tokenized, query_terms)
    return [float(score) for score in BM25Okapi(tokenized).get_scores(query_terms)]


def _bm25_okapi(documents: list[list[str]], query_terms: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 Okapi, written out: the IDF and the length normalisation ``rank_bm25`` uses."""
    count = len(documents)
    lengths = [len(document) for document in documents]
    average = (sum(lengths) / count) if count else 0.0
    scores = [0.0] * count
    for term in set(query_terms):
        containing = sum(1 for document in documents if term in document)
        if containing == 0:
            continue
        # The same ``+0.5`` smoothing rank_bm25 applies, so the two agree on a term nobody carries.
        idf = math.log((count - containing + 0.5) / (containing + 0.5) + 1.0)
        for index, document in enumerate(documents):
            frequency = document.count(term)
            if frequency == 0:
                continue
            denominator = frequency + k1 * (1 - b + b * (lengths[index] / average if average else 0.0))
            scores[index] += idf * (frequency * (k1 + 1)) / denominator
    return scores
