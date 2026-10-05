"""The policy index a run's ``SEARCH_POLICY`` reads, and the gate that keeps it from reading the wrong one.

``docs/policy-rag.md:21-23`` states the whole contract this module exists to satisfy: pull the named immutable
bundle, build a generation, verify hash and dimension, mark READY, and let a run bind to a READY index — and
"索引未就绪不搜旧版本" (the acceptance criterion in ``tasks/todo.md``). Three decisions follow from that, and
each is the reason for a piece of shape below.

**Readiness is per pinned bundle, and the pinned bundle is what a run asks for.** The run was dispatched with
``policy_manifest.bundle_ids`` and a ``manifest_hash``. Retrieval therefore does not search "the policy index";
it searches *the bundles this run is pinned to*, and each of them has to be READY at exactly the
``manifest_hash`` the dispatch named. A bundle that is missing, still BUILDING, FAILED, or READY for a
*stale or newer* hash produces :class:`PolicyIndexNotReadyError` — not an empty result, and never a search of
the generation that happens to be there. The difference matters because the two failure modes look identical
downstream: "no rule matched" and "the index was not ready" both read as "the policy does not say". This is
also why the refusal carries the reason and the hash, so a caller can retry until its deadline or escalate
(``docs/policy-rag.md:23``) rather than guess.

**Hard filters run before ranking, and they are not tunable.** ``docs/policy-rag.md:15``: 先按
merchant/category/manifest/bundle/version硬过滤，再做 dense cosine. So the candidate set is decided by the
filters and the ranking only orders what survives them. A "ranking that usually gets it right" is the failure
this prevents: a M-1001 run must not be able to retrieve a M-2002 rule *at all*, however similar the text.

**Both paths are here, and neither is a fallback for the other.** ``dense`` ranks by cosine over real
embeddings; ``bm25`` is the offline baseline (``docs/policy-rag.md:17``). :meth:`PolicyIndex.search` takes the
path as an argument rather than choosing: a caller that could get BM25 by asking for dense and silently
degrading would make every dense number in a report unfalsifiable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

from resolveflow.contracts.canonical import canonical_bytes
from resolveflow.policies.chunking import Chunk, chunks_of_bundle
from resolveflow.policies.retrieval import (
    Embedder,
    EmbeddingUnavailableError,
    bm25_scores,
    cosine_similarity,
)
from resolveflow.runtime.db import Database

__all__ = [
    "GENERATION_READY",
    "GENERATION_BUILDING",
    "GENERATION_FAILED",
    "MAX_TOP_K",
    "PolicyBundleIngestion",
    "PolicyChunkRow",
    "PolicyGeneration",
    "PolicyHit",
    "PolicyIndex",
    "PolicyIndexNotReadyError",
    "PolicySearchPath",
    "ServedBundle",
    "lineage_hash",
]

#: A generation's three states. BUILDING is written before any chunk is, so a crash mid-ingestion leaves a row
#: that says so rather than a half-index that looks complete.
GENERATION_BUILDING: Final = "BUILDING"
GENERATION_READY: Final = "READY"
GENERATION_FAILED: Final = "FAILED"

#: ``docs/agent-spec.md:16``: top_k<=5. Repeated here so the index refuses an over-large request itself rather
#: than trusting the action ABI's check to have run — the two are different boundaries and both are real.
MAX_TOP_K: Final = 5

#: The two paths, named rather than booleans, because a report has to say which one produced a number.
PolicySearchPath = Literal["dense", "bm25"]


def _validate_vector(vector: list[float], dimension: int) -> None:
    """Malformed embeddings are an index/encoder failure, never a policy miss."""
    if (len(vector) != dimension or not vector or any(not math.isfinite(v) for v in vector)
            or not any(v != 0 for v in vector)):
        raise ValueError("embedding vector must have the declared dimension, finite values and nonzero norm")


class PolicyIndexNotReadyError(RuntimeError):
    """A run asked for policy it is pinned to, and there is no READY generation at that hash.

    Carries the reason in the message, the run's own ``reason_code``, and in :attr:`hash_mismatch` whether a
    generation for the same bundle exists at a *different* hash. That distinction is the one an operator needs:
    "nobody indexed this bundle" is a deployment problem, while "indexed at a different hash" means the index is
    stale relative to the policy the case was pinned to, and re-indexing fixes it.

    The code is a property of the exception — the spelling :class:`~resolveflow.harness.actions.ActionRefusedError`
    already uses — so that every layer turning this refusal into a record reports the same one: the loop's stop
    reason and the trajectory entry become the same fact instead of two spellings of it. The first version of the
    shared local-read bridge defaulted the code to ``REFUSED`` and the two disagreed, which a test comparing them
    caught.
    """

    @property
    def reason_code(self) -> str:
        # Imported inside the property: `policies` is used by the ingestion script, which has no business importing
        # the harness loop at module scope.
        from resolveflow.harness.control import REASON_POLICY_INDEX_UNAVAILABLE

        return REASON_POLICY_INDEX_UNAVAILABLE

    def __init__(self, message: str, *, hash_mismatch: bool = False) -> None:
        super().__init__(message)
        self.hash_mismatch = hash_mismatch


@dataclass(frozen=True, slots=True)
class ServedBundle:
    """One bundle, exactly as Java served it through ``GET /internal/v1/policies/{bundle_id}``.

    The ingestion path takes this rather than a local file parse. ``manifest_hash`` is Java's own value,
    carried verbatim: a hash recomputed here from a local copy would verify the copy against itself and prove
    nothing about what Java will re-check a citation against.
    """

    bundle_id: str
    merchant_id: str
    version: str
    manifest_hash: str
    safety_epoch: int
    rules: list[dict[str, Any]]

    def chunks(self) -> tuple[Chunk, ...]:
        return chunks_of_bundle(self.bundle_id, self.rules)


@dataclass(frozen=True, slots=True)
class PolicyGeneration:
    """A built index generation, as stored."""

    generation_id: str
    bundle_id: str
    merchant_id: str
    version: str
    manifest_hash: str
    lineage_hash: str
    status: str
    embedding_model: str | None
    embedding_revision: str | None
    embedding_dimension: int | None
    chunk_count: int
    built_at: dt.datetime


@dataclass(frozen=True, slots=True)
class PolicyHit:
    """One retrieved rule, with everything a citation needs and everything a report wants to check.

    The citation members come from the *stored* row rather than being recomputed at retrieval time, because
    the stored value is what the generation was built from; a hit that recomputed its own hash could agree
    with itself while disagreeing with the copy Java holds.
    """

    bundle_id: str
    merchant_id: str
    version: str
    manifest_hash: str
    rule_id: str
    chunk_id: str
    content_hash: str
    title: str
    text: str
    score: float
    path: PolicySearchPath

    @property
    def source_ref(self) -> str:
        """The controlled reference form of this rule (``namespace:rest``, never a URL)."""
        return f"policy:{self.bundle_id}/{self.chunk_id}"

    def citation(self) -> dict[str, str]:
        """The ``PolicyRef`` members a proposal carries (``docs/policy-rag.md:25``)."""
        return {
            "bundle_id": self.bundle_id,
            "version": self.version,
            "rule_id": self.rule_id,
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
        }


@dataclass(slots=True)
class PolicyChunkRow:
    """A stored chunk, as read back for ranking.

    Not frozen, unlike every other small record in this module, and for a reason worth stating: ranking is the
    one thing here that is *mutating work in progress* — the two paths score the same candidate list in place
    and the caller sorts it. A frozen row made that a ``FrozenInstanceError`` at ranking time, which is the
    kind of shape change a `# type: ignore` would have hidden rather than fixed.
    """

    bundle_id: str
    merchant_id: str
    version: str
    manifest_hash: str
    chunk_id: str
    rule_id: str
    title: str
    text: str
    content_hash: str
    embedding: list[float] | None
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class PolicyBundleIngestion:
    """What one bundle's ingestion did, so a report can state it without re-reading the database."""

    bundle_id: str
    generation_id: str
    lineage_hash: str
    chunk_count: int
    replaced_generation: str | None


def lineage_hash(bundle: ServedBundle, chunks: tuple[Chunk, ...]) -> str:
    """SHA-256 over what was ingested: the bundle's identity plus every chunk in order.

    Distinct from ``manifest_hash`` on purpose. ``manifest_hash`` is Java's statement about the bundle;
    this is this side's statement about the *rows it wrote* — so an ingestion that dropped a rule, reordered
    them, or wrote half a bundle changes this hash while the bundle's own hash is untouched. Without it,
    "the index matches the bundle" would only ever be checked by looking at the bundle.
    """
    document = {
        "bundle_id": bundle.bundle_id,
        "merchant_id": bundle.merchant_id,
        "version": bundle.version,
        "manifest_hash": bundle.manifest_hash,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "rule_id": chunk.rule_id,
                "position": chunk.position,
                "title": chunk.title,
                "text": chunk.text,
                "content_hash": chunk.content_hash,
            }
            for chunk in chunks
        ],
    }
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


class PolicyIndex:
    """The policy index in ``agent_db``: build generations, and search the ones a run is pinned to.

    One object per database view rather than module state, for the same reason the run budget is an object:
    a test gets its own schema (``runtime/db.py``), and module-level state would leak one test's index into
    another's and make "the index was not ready" untestable.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------------ building

    def build(
        self,
        bundle: ServedBundle,
        *,
        embedder: Embedder | None = None,
        generation_id: str | None = None,
        now: dt.datetime | None = None,
        replace: bool = False,
    ) -> PolicyBundleIngestion:
        """Index one served bundle, and mark the generation READY only after every chunk is written.

        ``replace`` retires the bundle's previous READY generation in the same transaction. It is off by
        default because replacing is a deployment decision with a consequence: a run already dispatched at the
        old hash would stop finding its index. Off by default means two generations coexist, which is exactly
        what an in-flight run needs — and it is why the pinned ``manifest_hash``, not the bundle id, is what a
        search gates on.

        ``embedder=None`` builds the lexical-only index: ``embedding`` stays NULL and the dense path refuses
        for this generation rather than returning nothing. Refusing is the honest outcome; a dense search over
        rows with no vectors would report "0 results" for a corpus that was never embedded.
        """
        chunks = bundle.chunks()
        lineage = lineage_hash(bundle, chunks)
        generation = generation_id or uuid.uuid4().hex
        moment = now or dt.datetime.now(dt.UTC)

        vectors: list[list[float] | None] = [None] * len(chunks)
        dimension: int | None = None
        model: str | None = None
        revision: str | None = None
        if embedder is not None:
            texts = [chunk.embedded_text for chunk in chunks]
            embedded: list[list[float] | None] = list(embedder.embed(texts))
            if len(embedded) != len(chunks):
                raise ValueError(
                    f"the embedder returned {len(embedded)} vectors for {len(chunks)} chunks; refusing to "
                    "guess which chunk a vector belongs to"
                )
            for vector in embedded:
                if vector is None or len(vector) != embedder.dimension:
                    raise ValueError(
                        f"the embedder declares {embedder.dimension} dimensions but returned "
                        f"{'nothing' if vector is None else len(vector)}; the generation records a dimension, "
                        "so a mismatch has to stop here"
                    )
                _validate_vector(vector, embedder.dimension)
            vectors = embedded
            dimension = embedder.dimension
            model = embedder.model
            revision = embedder.revision

        with self._database.connection() as connection:
            with connection.transaction():
                previous = self._ready_generation(connection, bundle.bundle_id)
                connection.execute(
                    """
                    INSERT INTO policy_index_generation (
                        generation_id, bundle_id, merchant_id, version, safety_epoch, manifest_hash,
                        lineage_hash, status, embedding_model, embedding_revision, embedding_dimension,
                        chunk_count, built_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        generation,
                        bundle.bundle_id,
                        bundle.merchant_id,
                        bundle.version,
                        bundle.safety_epoch,
                        bundle.manifest_hash,
                        lineage,
                        GENERATION_BUILDING,
                        model,
                        revision,
                        dimension,
                        len(chunks),
                        moment,
                    ),
                )
                for chunk, vector in zip(chunks, vectors, strict=True):
                    connection.execute(
                        """
                        INSERT INTO policy_index_chunk (
                            generation_id, bundle_id, chunk_id, rule_id, position, title, text,
                            content_hash, embedded_text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            generation,
                            bundle.bundle_id,
                            chunk.chunk_id,
                            chunk.rule_id,
                            chunk.position,
                            chunk.title,
                            chunk.text,
                            chunk.content_hash,
                            chunk.embedded_text,
                            vector,
                        ),
                    )
                # READY last, inside the same transaction as the chunks: a generation that says READY while a
                # chunk is missing would be a search that silently returns fewer rules than the policy has.
                connection.execute(
                    "UPDATE policy_index_generation SET status = %s WHERE generation_id = %s AND bundle_id = %s",
                    (GENERATION_READY, generation, bundle.bundle_id),
                )
                if replace and previous is not None and previous != generation:
                    connection.execute(
                        """
                        UPDATE policy_index_generation SET status = %s
                         WHERE generation_id = %s AND bundle_id = %s
                        """,
                        (GENERATION_BUILDING, previous, bundle.bundle_id),
                    )
            return PolicyBundleIngestion(
                bundle_id=bundle.bundle_id,
                generation_id=generation,
                lineage_hash=lineage,
                chunk_count=len(chunks),
                replaced_generation=previous if replace else None,
            )

    def fail(self, bundle_id: str, generation_id: str, reason: str) -> None:
        """Mark a generation FAILED, so an aborted build cannot be mistaken for a partial READY one."""
        with self._database.connection() as connection:
            connection.execute(
                """
                UPDATE policy_index_generation SET status = %s
                 WHERE generation_id = %s AND bundle_id = %s
                """,
                (GENERATION_FAILED, generation_id, bundle_id),
            )

    def generation_for(self, bundle_id: str, manifest_hash: str) -> PolicyGeneration | None:
        """The READY generation for a bundle at exactly this hash, or ``None``.

        The hash is part of the lookup rather than a check after it: "find the ready generation, then compare
        hashes" has a window in which the answer is the wrong one, and this method's answer decides which text
        a run cites.
        """
        with self._database.connection() as connection:
            row = self._ready_generation_row(connection, bundle_id, manifest_hash)
        return _generation_of(row) if row else None

    def generations(self, bundle_id: str | None = None) -> list[PolicyGeneration]:
        """Every generation, newest first: what a report or an operator reads."""
        with self._database.connection() as connection:
            if bundle_id is None:
                rows = connection.execute(
                    "SELECT * FROM policy_index_generation ORDER BY built_at DESC, bundle_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM policy_index_generation WHERE bundle_id = %s ORDER BY built_at DESC",
                    (bundle_id,),
                ).fetchall()
        return [_generation_of(row) for row in rows]

    # ------------------------------------------------------------------ searching

    def require_ready(self, bundle_ids: list[str], manifest_hash: str) -> list[PolicyGeneration]:
        """Every pinned bundle, confirmed READY at ``manifest_hash`` — or a refusal that says why.

        This is the gate the acceptance criterion is about. It is a separate method from :meth:`search` so a
        caller (and a test) can ask the question without searching, and so ``search`` cannot accidentally
        proceed when only *some* of the pinned bundles are ready: a run pinned to two bundles and served one
        of them would cite half a policy set.
        """
        if not bundle_ids:
            raise PolicyIndexNotReadyError("a policy search needs at least one pinned bundle id")
        if not manifest_hash:
            raise PolicyIndexNotReadyError("a policy search needs the manifest hash the run is pinned to")
        ready: list[PolicyGeneration] = []
        with self._database.connection() as connection:
            for bundle_id in bundle_ids:
                row = self._ready_generation_row(connection, bundle_id, manifest_hash)
                if row is None:
                    raise self._not_ready(connection, bundle_id, manifest_hash)
                ready.append(_generation_of(row))
        return ready

    def _not_ready(
        self, connection: Any, bundle_id: str, manifest_hash: str
    ) -> PolicyIndexNotReadyError:
        """Turn "no READY row" into the most specific refusal the stored rows support."""
        others = connection.execute(
            "SELECT generation_id, manifest_hash, status FROM policy_index_generation WHERE bundle_id = %s",
            (bundle_id,),
        ).fetchall()
        if not others:
            return PolicyIndexNotReadyError(
                f"bundle {bundle_id} has no index generation at all; nothing to search and no older policy "
                "to fall back to (docs/policy-rag.md:23)"
            )
        statuses = ", ".join(f"{row['generation_id']}={row['status']}@{row['manifest_hash'][:12]}" for row in others)
        return PolicyIndexNotReadyError(
            f"bundle {bundle_id} has no READY generation at manifest_hash {manifest_hash}; stored: {statuses}. "
            "A run pinned to this hash may retry until its deadline or escalate — it may not search another "
            "version (docs/policy-rag.md:23)",
            hash_mismatch=any(row["manifest_hash"] != manifest_hash for row in others),
        )

    def search(
        self,
        *,
        merchant_id: str,
        bundle_ids: list[str],
        manifest_hash: str,
        query: str,
        path: PolicySearchPath,
        top_k: int = MAX_TOP_K,
        embedder: Embedder | None = None,
    ) -> list[PolicyHit]:
        """Rank the pinned bundles' rules for ``query``, after the hard filters.

        Filters, in the order they are applied and none of them optional:

        1. **the pinned bundles** — the run's own ``bundle_ids``;
        2. **the pinned manifest hash** — enforced by :meth:`require_ready`, which is what stops a
           newer-but-READY generation from being searched;
        3. **the merchant** — the run's own, checked against each generation's recorded merchant. It is
           redundant with (1) in a correct deployment and that is the point: it is the filter that must hold
           even if a bundle id were ever mis-pinned, and it is the one a test can falsify by pinning the
           wrong bundle.
        """
        if path not in ("dense", "bm25"):
            raise ValueError(f"{path!r} is not a retrieval path; dense and bm25 are the only two")
        if top_k < 1 or top_k > MAX_TOP_K:
            raise ValueError(f"top_k must be 1..{MAX_TOP_K} (docs/agent-spec.md:16)")
        ready = self.require_ready(bundle_ids, manifest_hash)
        by_bundle = {generation.bundle_id: generation for generation in ready}
        if any(generation.merchant_id != merchant_id for generation in ready):
            raise PolicyIndexNotReadyError(
                f"the run's merchant {merchant_id} does not match any pinned bundle's merchant "
                f"({sorted({generation.merchant_id for generation in ready})}); a run may not retrieve "
                "another merchant's policy (docs/policy-rag.md:15)"
            )

        if path == "dense" and any(g.embedding_model is None for g in ready):
            raise PolicyIndexNotReadyError("selected generation has no embedding; build a dense index first")
        if path == "dense" and embedder is not None and any(
            (g.embedding_model, g.embedding_revision, g.embedding_dimension)
            != (embedder.model, embedder.revision, embedder.dimension) for g in ready
        ):
            raise PolicyIndexNotReadyError("query embedding model/revision/dimension differs from the selected index")
        rows = self._chunks_for(list(by_bundle), manifest_hash,
                                generation_ids=[g.generation_id for g in ready])
        if any(sum(row.bundle_id == g.bundle_id for row in rows) != g.chunk_count for g in ready):
            raise PolicyIndexNotReadyError("selected index chunk count differs from READY metadata")
        if path == "dense":
            scored = self._rank_dense(rows, query, embedder)
        else:
            scored = self._rank_bm25(rows, query)
        scored.sort(key=lambda row: (-row.score, row.bundle_id, row.chunk_id))
        return [
            PolicyHit(
                bundle_id=row.bundle_id,
                merchant_id=row.merchant_id,
                version=row.version,
                manifest_hash=row.manifest_hash,
                rule_id=row.rule_id,
                chunk_id=row.chunk_id,
                content_hash=row.content_hash,
                title=row.title,
                text=row.text,
                score=row.score,
                path=path,
            )
            for row in scored[:top_k]
        ]

    def _rank_dense(
        self, rows: list[PolicyChunkRow], query: str, embedder: Embedder | None
    ) -> list[PolicyChunkRow]:
        """Cosine over real embeddings, or a refusal — never a silent BM25.

        The vectors come back from the database, not from an in-process cache: the stored vector is what the
        generation recorded, and re-embedding at query time would make a report's numbers depend on the model
        being loadable rather than on what was indexed. The **query** is embedded here, so the embedder must
        be the same one the generation was built with — which is why the generation records its model and
        revision, and why a mismatch is refused below rather than ranked.
        """
        if embedder is None:
            raise EmbeddingUnavailableError(
                "a dense search needs an embedder; pass the one the generation was built with. There is no "
                "default here on purpose: a query embedded by a different model than the corpus would rank "
                "meaninglessly while looking like a real result (docs/policy-rag.md:19)"
            )
        missing = [row for row in rows if row.embedding is None]
        if missing:
            raise PolicyIndexNotReadyError(
                f"{len(missing)} of {len(rows)} indexed chunks have no embedding "
                f"(generation was built without one); the dense path refuses rather than falling back to a "
                "different ranking (docs/policy-rag.md:23)"
            )
        query_vectors = embedder.embed([query])
        if len(query_vectors) != 1:
            raise ValueError("query encoder must return exactly one vector")
        query_vector = query_vectors[0]
        _validate_vector(query_vector, embedder.dimension)
        for row in rows:
            assert row.embedding is not None  # checked above; asserted for the type checker
            try:
                _validate_vector(row.embedding, embedder.dimension)
            except ValueError as failure:
                raise PolicyIndexNotReadyError("stored embedding vector is invalid; rebuild the index") from failure
            row.score = cosine_similarity(query_vector, row.embedding)
        return rows

    def _rank_bm25(self, rows: list[PolicyChunkRow], query: str) -> list[PolicyChunkRow]:
        """BM25 over the same filtered candidates. The offline baseline (``docs/policy-rag.md:17``)."""
        scores = bm25_scores([row.text for row in rows], query)
        for row, score in zip(rows, scores, strict=True):
            row.score = score
        return rows

    # ------------------------------------------------------------------ internals

    def _chunks_for(
        self, bundle_ids: list[str], manifest_hash: str, *, generation_ids: list[str],
    ) -> list[PolicyChunkRow]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT c.bundle_id, c.chunk_id, c.rule_id, c.title, c.text, c.content_hash, c.embedding,
                       g.merchant_id, g.version
                  FROM policy_index_chunk AS c
                  JOIN policy_index_generation AS g
                    ON g.generation_id = c.generation_id AND g.bundle_id = c.bundle_id
                 WHERE c.bundle_id = ANY(%s)
                   AND g.manifest_hash = %s
                   AND g.status = %s
                   AND g.generation_id = ANY(%s)
                 ORDER BY c.bundle_id, c.position
                """,
                (bundle_ids, manifest_hash, GENERATION_READY, generation_ids),
            ).fetchall()
        return [
            PolicyChunkRow(
                bundle_id=row["bundle_id"],
                merchant_id=row["merchant_id"],
                version=row["version"],
                manifest_hash=manifest_hash,
                chunk_id=row["chunk_id"],
                rule_id=row["rule_id"],
                title=row["title"],
                text=row["text"],
                content_hash=row["content_hash"],
                embedding=list(row["embedding"]) if row["embedding"] is not None else None,
            )
            for row in rows
        ]

    @staticmethod
    def _ready_generation_row(connection: Any, bundle_id: str, manifest_hash: str) -> Any:
        return connection.execute(
            """
            SELECT * FROM policy_index_generation
             WHERE bundle_id = %s AND manifest_hash = %s AND status = %s
             ORDER BY built_at DESC, generation_id
             LIMIT 1
            """,
            (bundle_id, manifest_hash, GENERATION_READY),
        ).fetchone()

    @staticmethod
    def _ready_generation(connection: Any, bundle_id: str) -> str | None:
        row = connection.execute(
            "SELECT generation_id FROM policy_index_generation WHERE bundle_id = %s AND status = %s LIMIT 1",
            (bundle_id, GENERATION_READY),
        ).fetchone()
        return row["generation_id"] if row else None


def _generation_of(row: dict[str, Any]) -> PolicyGeneration:
    return PolicyGeneration(
        generation_id=row["generation_id"],
        bundle_id=row["bundle_id"],
        merchant_id=row["merchant_id"],
        version=row["version"],
        manifest_hash=row["manifest_hash"],
        lineage_hash=row["lineage_hash"],
        status=row["status"],
        embedding_model=row["embedding_model"],
        embedding_revision=row["embedding_revision"],
        embedding_dimension=row["embedding_dimension"],
        chunk_count=row["chunk_count"],
        built_at=row["built_at"],
    )


def served_bundle_of(payload: dict[str, Any]) -> ServedBundle:
    """A served ``PolicyBundle`` body, as :class:`ServedBundle`.

    Strict about the members it needs and about the merchant: C07.1 made ``merchant_id`` part of the bundle on
    the wire, so a payload without one is a response from before that change and is refused rather than
    indexed with an unknown owner — an index whose merchant is blank would satisfy every merchant filter.
    """
    required = ("bundle_id", "merchant_id", "version", "manifest_hash", "rules")
    missing = [member for member in required if member not in payload]
    if missing:
        raise ValueError(f"a served bundle is missing {missing}; got {sorted(payload)}")
    manifest_hash = payload["manifest_hash"]
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        raise ValueError("a served bundle's manifest_hash must be a sha-256 hex digest")
    rules = payload["rules"]
    if not isinstance(rules, list):
        raise ValueError("a served bundle's rules must be a list")
    return ServedBundle(
        bundle_id=str(payload["bundle_id"]),
        merchant_id=str(payload["merchant_id"]),
        version=str(payload["version"]),
        manifest_hash=manifest_hash,
        safety_epoch=int(payload.get("safety_epoch") or 0),
        rules=rules,
    )
