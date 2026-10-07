"""Pinned experimental ranking adapter for the resume evaluation, never a production default."""

from resolveflow.policies.index import PolicyHit, PolicyIndex
from resolveflow.policies.retrieval import bm25_scores, cosine_similarity


class ExperimentalPolicyIndex(PolicyIndex):
    def __init__(self, database, variant, reranker=None):
        super().__init__(database)
        self.variant = variant
        self.reranker = reranker

    def search(self, **kwargs):
        if self.variant == "B":
            return super().search(**kwargs)
        # Reuse all production pin/merchant/generation/count validations before experimental ranking.
        validation = dict(kwargs, path="bm25", top_k=5, embedder=None)
        super().search(**validation)
        selected = kwargs.get("generation_ids")
        generations = selected or {
            g.bundle_id: g.generation_id
            for g in self.require_ready(kwargs["bundle_ids"], kwargs["manifest_hash"])
        }
        rows = self._chunks_for(
            kwargs["bundle_ids"],
            kwargs["manifest_hash"],
            generation_ids=list(generations.values()),
        )
        chunks = {r.chunk_id: r for r in rows}
        query = kwargs["query"]
        lexical = sorted(
            zip(rows, bm25_scores([r.text for r in rows], query), strict=True),
            key=lambda pair: (-pair[1], pair[0].chunk_id),
        )
        if self.variant in ("A", "C"):
            ranked = lexical[:20]
        else:
            vector = kwargs["embedder"].embed([query])[0]
            dense = sorted(
                [(r, cosine_similarity(vector, r.embedding)) for r in rows],
                key=lambda pair: (-pair[1], pair[0].chunk_id),
            )[:20]
            scores = {}
            for ranking in (dense, [(r, s) for r, s in lexical if s > 0][:20]):
                for position, (row, _) in enumerate(ranking, 1):
                    scores[row.chunk_id] = scores.get(row.chunk_id, 0) + 1 / (
                        60 + position
                    )
            ranked = sorted(
                [(chunks[cid], s) for cid, s in scores.items()],
                key=lambda pair: (-pair[1], pair[0].chunk_id),
            )[:20]
        if self.variant in ("C", "E"):
            values = self.reranker.predict(
                [(query, r.text) for r, _ in ranked],
                batch_size=8,
                show_progress_bar=False,
            )
            ranked = sorted(
                [(r, float(s)) for (r, _), s in zip(ranked, values, strict=True)],
                key=lambda pair: (-pair[1], pair[0].chunk_id),
            )
        return [
            PolicyHit(
                bundle_id=r.bundle_id,
                merchant_id=r.merchant_id,
                version=r.version,
                manifest_hash=r.manifest_hash,
                rule_id=r.rule_id,
                chunk_id=r.chunk_id,
                content_hash=r.content_hash,
                title=r.title,
                text=r.text,
                score=s,
                path=kwargs["path"],
            )
            for r, s in ranked[: kwargs["top_k"]]
        ]
