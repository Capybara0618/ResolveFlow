"""Policy retrieval for the Agent (C07): the index a run's ``SEARCH_POLICY`` reads.

Two files matter beyond this one, and they are separate because they answer different questions:

* :mod:`resolveflow.policies.chunking` — what a citable unit is, and the hashes that make a citation
  checkable by the service that owns the policy text;
* :mod:`resolveflow.policies.index` — the index itself, its READY gate, and the hard filters.

:mod:`resolveflow.policies.retrieval` holds the two ranking paths (real embeddings, and the BM25 baseline).

**Where the text comes from, because it is the design decision this package is built around.** The
authoritative rule text is Java's: it is stored in ``policy_bundle``/``policy_rule`` and served by
``GET /internal/v1/policies/{bundle_id}`` under the ``policy:read`` scope. Nothing in the repository's
``fixtures/policies/bundles/`` is read by this package at retrieval time — those files are the *input to the
controlled import*, and a hash this side derived from them would verify this side's own parsing. So the index
is populated by ``scripts/policy_index_ingest.py``, which performs that read and carries Java's own
``manifest_hash`` through verbatim (see :func:`resolveflow.policies.index.served_bundle_of`). That is what
keeps "the run cited a rule" and "Java will re-check that citation" statements about the same bytes.
"""

from resolveflow.policies.chunking import Chunk, ChunkingError, chunk_id_for, chunks_of_bundle
from resolveflow.policies.index import (
    GENERATION_BUILDING,
    GENERATION_FAILED,
    GENERATION_READY,
    MAX_TOP_K,
    PolicyBundleIngestion,
    PolicyGeneration,
    PolicyHit,
    PolicyIndex,
    PolicyIndexNotReadyError,
    PolicySearchPath,
    ServedBundle,
    lineage_hash,
    served_bundle_of,
)
from resolveflow.policies.retrieval import (
    BM25_BASELINE_NOTE,
    EMBEDDING_DIMENSION,
    EMBEDDING_LICENSE,
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    Embedder,
    EmbeddingUnavailableError,
    SentenceTransformerEmbedder,
    bm25_scores,
    cosine_similarity,
    embedder,
    tokenize,
)

__all__ = [
    "BM25_BASELINE_NOTE",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_LICENSE",
    "EMBEDDING_MODEL",
    "EMBEDDING_REVISION",
    "GENERATION_BUILDING",
    "GENERATION_FAILED",
    "GENERATION_READY",
    "MAX_TOP_K",
    "Chunk",
    "ChunkingError",
    "Embedder",
    "EmbeddingUnavailableError",
    "PolicyBundleIngestion",
    "PolicyGeneration",
    "PolicyHit",
    "PolicyIndex",
    "PolicyIndexNotReadyError",
    "PolicySearchPath",
    "SentenceTransformerEmbedder",
    "ServedBundle",
    "bm25_scores",
    "chunk_id_for",
    "chunks_of_bundle",
    "cosine_similarity",
    "embedder",
    "lineage_hash",
    "served_bundle_of",
    "tokenize",
]
