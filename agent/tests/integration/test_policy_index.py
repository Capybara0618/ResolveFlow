"""The policy index: the READY gate, the hard filters, and the citations (C07.1).

The tests are grouped by the two failure modes this slice exists to exclude, because both would otherwise
ship as a working-looking feature:

* **searching the wrong version** — a run pinned to the September manifest must not retrieve August's rules,
  and when its own bundle is not indexed it must be *told*, not handed another version's text
  (``docs/policy-rag.md:23``; the acceptance criterion 索引未就绪不搜旧版本);
* **retrieving across merchants** — the second merchant exists in the fixtures precisely so this can be
  falsified rather than argued.

Everything here runs against the real database in a schema of the test's own (``agent_db``), because the
READY gate is a property of *stored rows*: a fake store would let the gate pass while the SQL that implements
it did not.
"""

from __future__ import annotations

import pytest

from resolveflow.policies import (
    GENERATION_BUILDING,
    PolicyIndex,
    PolicyIndexNotReadyError,
    ServedBundle,
    served_bundle_of,
)
from resolveflow.policies.retrieval import EmbeddingUnavailableError
from resolveflow.runtime.db import Database

#: One merchant's two versions of the same bundle, so "the index holds a different version of the very bundle
#: this run is pinned to" is expressible — that, and not "two unrelated bundles", is the state the READY gate
#: has to refuse. Two merchants are here because the merchant filter has to be falsifiable, and the two share a
#: rule id *and* its wording so a ranking-only implementation would return the other merchant's chunk happily.
_LOST_RULE = {
    "rule_id": "R-LOST-001",
    "title": "承运商判定丢失",
    "text": "承运商结论为 LOST 且无有效签收记录时，可全额退款。",
}

LOGISTICS_AUGUST = ServedBundle(
    bundle_id="policy-logistics-2026.09",
    merchant_id="M-1001",
    version="2026.08",
    manifest_hash="a" * 64,
    safety_epoch=1,
    rules=[
        dict(_LOST_RULE),
        {"rule_id": "R-SIGNED-001", "title": "已签收", "text": "存在有效签收记录时不予退款，须人工核验。"},
    ],
)
LOGISTICS_SEPTEMBER = ServedBundle(
    bundle_id="policy-logistics-2026.09",
    merchant_id="M-1001",
    version="2026.09",
    manifest_hash="b" * 64,
    safety_epoch=2,
    rules=[
        dict(_LOST_RULE),
        {
            "rule_id": "R-NOSCAN-7D",
            "title": "七天无扫描",
            "text": "承运商无有效签收且连续 7 天无扫描记录时，视同丢失，可全额退款。",
        },
    ],
)
DAMAGE_SEPTEMBER = ServedBundle(
    bundle_id="policy-damage-2026.09",
    merchant_id="M-2002",
    version="2026.09",
    manifest_hash="c" * 64,
    safety_epoch=2,
    rules=[
        {"rule_id": "R-DMG-001", "title": "到货破损", "text": "客户提交的到货破损图片经核验有效时，可全额退款。"},
        # The same rule id and the same wording as M-1001's: this is the chunk a ranking-only implementation
        # would hand a M-1001 run.
        dict(_LOST_RULE),
    ],
)


@pytest.fixture()
def index(agent_db: Database) -> PolicyIndex:
    return PolicyIndex(agent_db)


def search(index: PolicyIndex, bundle: ServedBundle, query: str, **overrides: object) -> list[object]:
    """A ``bm25`` search over one bundle, which is the path that needs no embedder.

    The dense path's ranking is exercised by the evaluation run with the real model
    (``scripts/policy_search_eval.py``); what these tests are about — the gate and the filters — is decided
    before either ranking happens, so testing it through the lexical path tests the same decision.
    """
    arguments: dict[str, object] = {
        "merchant_id": bundle.merchant_id,
        "bundle_ids": [bundle.bundle_id],
        "manifest_hash": bundle.manifest_hash,
        "query": query,
        "path": "bm25",
    }
    arguments.update(overrides)
    return index.search(**arguments)  # type: ignore[arg-type]


def test_a_built_bundle_is_ready_and_searchable(index: PolicyIndex) -> None:
    ingestion = index.build(LOGISTICS_SEPTEMBER)

    assert ingestion.chunk_count == len(LOGISTICS_SEPTEMBER.rules)
    generation = index.generation_for(LOGISTICS_SEPTEMBER.bundle_id, LOGISTICS_SEPTEMBER.manifest_hash)
    assert generation is not None
    assert generation.status == "READY"
    assert generation.chunk_count == 2

    hits = search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")
    assert hits, "a built bundle must be searchable"
    # **Ranking is not asserted here, and that is deliberate.** The first version asserted that the lost-parcel
    # rule came first, and it passed until `jieba` was installed: the lexical tokeniser changed, the ranking
    # changed with it, and the test went red although nothing about the index had. Which rule a *stub* bag of
    # words puts first is not a property this slice owns — it is the real model's, measured in
    # `reports/c071-policy-index/retrieval-eval-both.txt` on the frozen query set. What this test owns is the
    # plumbing: that the search runs, returns citable hits, and reports them as the pinned bundle's.
    assert {hit.bundle_id for hit in hits} == {LOGISTICS_SEPTEMBER.bundle_id}  # type: ignore[attr-defined]
    assert all(hit.content_hash and hit.chunk_id for hit in hits)  # type: ignore[attr-defined]


def test_a_run_pinned_to_an_unindexed_hash_is_refused_rather_than_given_another_version(
    index: PolicyIndex,
) -> None:
    """The acceptance criterion: 索引未就绪不搜旧版本.

    The bundle *is* indexed — at a different ``manifest_hash``. That is the real shape of this failure: a case
    was pinned to the version in force when it was opened, and this service's index has since moved on (a
    re-import, a model rebuild, a newer published version). The rules that are sitting right there are a
    different version's, and handing them over would be a silent policy downgrade whose citation named a
    bundle the case was never pinned to.

    A run pinned to ``LOGISTICS_AUGUST``'s hash must therefore be refused, even though
    ``policy-logistics-2026.09`` is READY and its text is nearly identical.
    """
    index.build(LOGISTICS_SEPTEMBER)

    with pytest.raises(PolicyIndexNotReadyError) as refusal:
        search(index, LOGISTICS_AUGUST, "承运商说件丢了")

    message = str(refusal.value)
    assert "no READY generation" in message
    assert LOGISTICS_AUGUST.manifest_hash in message
    # And it says what *is* stored, so an operator knows whether to re-index or to look for a deployment bug.
    assert LOGISTICS_SEPTEMBER.manifest_hash[:12] in message
    assert refusal.value.hash_mismatch is True


def test_a_bundle_nobody_indexed_says_so_rather_than_reporting_no_matches(index: PolicyIndex) -> None:
    """ "Nothing indexed" and "no rule matched" look identical downstream, and are not the same fact."""
    with pytest.raises(PolicyIndexNotReadyError, match="no index generation at all"):
        search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")


def test_every_pinned_bundle_has_to_be_ready_not_merely_one(index: PolicyIndex) -> None:
    """A run pinned to two bundles and served one of them would cite half a policy set."""
    index.build(LOGISTICS_SEPTEMBER)
    # DAMAGE_SEPTEMBER's hash is the run's second pin and it is not indexed, so the whole search is refused
    # rather than answered from the bundle that is ready.
    with pytest.raises(PolicyIndexNotReadyError, match="policy-damage-2026.09"):
        index.search(
            merchant_id="M-1001",
            bundle_ids=["policy-logistics-2026.09", "policy-damage-2026.09"],
            manifest_hash=LOGISTICS_SEPTEMBER.manifest_hash,
            query="承运商说件丢了",
            path="bm25",
        )


def test_a_generation_that_is_not_ready_is_not_searchable(index: PolicyIndex, agent_db: Database) -> None:
    """A BUILDING generation must not answer: it is a half-written index, not a small one."""
    index.build(LOGISTICS_SEPTEMBER)
    with agent_db.connection() as connection:
        connection.execute(
            "UPDATE policy_index_generation SET status = %s WHERE bundle_id = %s",
            (GENERATION_BUILDING, LOGISTICS_SEPTEMBER.bundle_id),
        )

    with pytest.raises(PolicyIndexNotReadyError):
        search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")


def test_a_second_generation_at_a_new_hash_does_not_replace_the_old_one(index: PolicyIndex) -> None:
    """An in-flight run pinned to the old hash keeps working while a newer version is indexed.

    This is why the gate keys on ``manifest_hash`` rather than on "the bundle's current generation": replacing
    in place would break a run that was dispatched a moment ago, which is the silent-switch failure in the
    other direction.
    """
    index.build(LOGISTICS_SEPTEMBER)
    newer = ServedBundle(
        bundle_id=LOGISTICS_SEPTEMBER.bundle_id,
        merchant_id=LOGISTICS_SEPTEMBER.merchant_id,
        version="2026.10",
        # Same bundle, a new version: a *different* manifest hash, which is exactly the state a re-import
        # produces.
        manifest_hash="d" * 64,
        safety_epoch=3,
        rules=[{"rule_id": "R-NEW", "title": "新版", "text": "新版规则：全额退款需人工核验。"}],
    )
    index.build(newer)

    old_hits = search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")
    assert {hit.rule_id for hit in old_hits} & {"R-LOST-001", "R-NOSCAN-7D"}  # type: ignore[attr-defined]
    new_hits = search(index, newer, "退款需人工核验")
    assert new_hits and new_hits[0].rule_id == "R-NEW"  # type: ignore[attr-defined]

    # Both generations are stored, so which one a citation came from stays answerable.
    assert {generation.version for generation in index.generations(LOGISTICS_SEPTEMBER.bundle_id)} == {
        "2026.09",
        "2026.10",
    }


def test_replace_retires_the_previous_generation(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER)
    newer = ServedBundle(
        bundle_id=LOGISTICS_SEPTEMBER.bundle_id,
        merchant_id=LOGISTICS_SEPTEMBER.merchant_id,
        version="2026.10",
        manifest_hash="d" * 64,
        safety_epoch=3,
        rules=[{"rule_id": "R-NEW", "title": "新版", "text": "新版规则。"}],
    )
    ingestion = index.build(newer, replace=True)

    assert ingestion.replaced_generation is not None
    with pytest.raises(PolicyIndexNotReadyError):
        search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")


def test_a_query_never_returns_another_merchant_s_rule(index: PolicyIndex) -> None:
    """The hard filter this slice's second merchant exists for.

    Both merchants have a rule with the *same* rule id and the *same* wording (R-LOST-001), so a search that
    only ranked would return the other one's chunk as a perfectly good answer: same words, different policy
    set, and a citation that names a bundle the case was never pinned to.
    """
    index.build(LOGISTICS_SEPTEMBER)
    index.build(DAMAGE_SEPTEMBER)

    hits = search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了")
    assert hits
    assert {hit.merchant_id for hit in hits} == {"M-1001"}  # type: ignore[attr-defined]
    assert {hit.bundle_id for hit in hits} == {"policy-logistics-2026.09"}  # type: ignore[attr-defined]


def test_a_run_pinned_to_another_merchant_s_bundle_is_refused(index: PolicyIndex) -> None:
    """The merchant is checked against the *pinned bundle's* merchant, not only used as a filter.

    Pinning the wrong bundle is a dispatcher bug; the refusal names both merchants so it reads as one.
    """
    index.build(DAMAGE_SEPTEMBER)

    with pytest.raises(PolicyIndexNotReadyError, match="another merchant"):
        search(index, DAMAGE_SEPTEMBER, "破损了", merchant_id="M-1001")


def test_top_k_is_bounded_here_as_well_as_in_the_action_abi(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER)

    with pytest.raises(ValueError, match="top_k"):
        search(index, LOGISTICS_SEPTEMBER, "退款", top_k=6)
    assert len(search(index, LOGISTICS_SEPTEMBER, "退款", top_k=1)) == 1


def test_an_unknown_retrieval_path_is_refused(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER)

    with pytest.raises(ValueError, match="not a retrieval path"):
        search(index, LOGISTICS_SEPTEMBER, "退款", path="hybrid")


def test_a_hit_carries_a_citation_java_can_recheck(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER)

    # The hit is *selected by identity*, not by rank: which rule a lexical stub puts first is the stub's
    # business (see `test_a_built_bundle_is_ready_and_searchable`). What matters is that whichever hit a run
    # cites carries members Java can recompute — and that the recomputation is Java's construction.
    hits = search(index, LOGISTICS_SEPTEMBER, "承运商结论为 LOST")
    hit = next(item for item in hits if item.rule_id == "R-LOST-001")

    assert hit.citation() == {
        "bundle_id": "policy-logistics-2026.09",
        "version": "2026.09",
        "rule_id": "R-LOST-001",
        "chunk_id": "c-01",
        "content_hash": hit.content_hash,
    }
    assert hit.source_ref == "policy:policy-logistics-2026.09/c-01"
    from resolveflow.contracts.canonical import content_hash

    assert hit.content_hash == content_hash(
        {
            "bundle_id": "policy-logistics-2026.09",
            "chunk_id": "c-01",
            "title": "承运商判定丢失",
            "text": "承运商结论为 LOST 且无有效签收记录时，可全额退款。",
        }
    )


def test_a_bundle_built_without_an_embedder_refuses_the_dense_path(index: PolicyIndex) -> None:
    """No silent BM25 behind a dense request: that would make every dense number in a report unfalsifiable."""
    index.build(LOGISTICS_SEPTEMBER)  # no embedder

    with pytest.raises(PolicyIndexNotReadyError, match="no embedding"):
        search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了", path="dense", embedder=_StubForDense())


def test_a_dense_search_needs_the_embedder_the_generation_was_built_with(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER, embedder=_StubForDense())

    with pytest.raises(EmbeddingUnavailableError, match="needs an embedder"):
        search(index, LOGISTICS_SEPTEMBER, "承运商说件丢了", path="dense")


def test_an_embedder_that_returns_the_wrong_number_of_vectors_stops_the_build(
    index: PolicyIndex, agent_db: Database
) -> None:
    """A vector silently attached to the wrong chunk would make ranking nonsense that still returns hits."""
    with pytest.raises(ValueError, match="refusing to guess"):
        index.build(LOGISTICS_SEPTEMBER, embedder=_StubForDense(return_count=1))
    # And nothing was left behind: a failed build must not leave a generation a run could bind to.
    assert index.generations(LOGISTICS_SEPTEMBER.bundle_id) == []


def test_an_embedder_with_the_wrong_dimension_stops_the_build(index: PolicyIndex, agent_db: Database) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        index.build(LOGISTICS_SEPTEMBER, embedder=_StubForDense(declared_dimension=8, actual_dimension=3))


def test_the_generation_records_the_embedding_it_used(index: PolicyIndex) -> None:
    index.build(LOGISTICS_SEPTEMBER, embedder=_StubForDense())

    generation = index.generation_for(LOGISTICS_SEPTEMBER.bundle_id, LOGISTICS_SEPTEMBER.manifest_hash)
    assert generation is not None
    # Recorded per generation, because it is what makes a model change a *new generation* rather than a
    # silent change of meaning for vectors already stored (docs/policy-rag.md:19).
    assert generation.embedding_model == "stub-embedder"
    assert generation.embedding_revision == "stub-revision-1"
    assert generation.embedding_dimension == 8


def test_the_lineage_hash_changes_when_a_chunk_changes_but_the_manifest_hash_does_not(index: PolicyIndex) -> None:
    """``lineage_hash`` is this side's statement about its own rows; ``manifest_hash`` is Java's."""
    first = index.build(LOGISTICS_SEPTEMBER)
    tampered = ServedBundle(
        bundle_id=LOGISTICS_SEPTEMBER.bundle_id,
        merchant_id=LOGISTICS_SEPTEMBER.merchant_id,
        version=LOGISTICS_SEPTEMBER.version,
        manifest_hash=LOGISTICS_SEPTEMBER.manifest_hash,  # Java's hash, unchanged
        safety_epoch=LOGISTICS_SEPTEMBER.safety_epoch,
        rules=[*LOGISTICS_SEPTEMBER.rules[:-1], {"rule_id": "R-X", "title": "改写", "text": "正文被改过。"}],
    )
    second = index.build(tampered)

    assert second.lineage_hash != first.lineage_hash
    assert second.bundle_id == first.bundle_id


def test_a_served_bundle_without_a_merchant_is_refused() -> None:
    """A response from before C07.1 has no merchant, and indexing it would make every merchant filter pass."""
    with pytest.raises(ValueError, match="merchant_id"):
        served_bundle_of(
            {
                "bundle_id": "policy-x",
                "version": "2026.09",
                "manifest_hash": "e" * 64,
                "safety_epoch": 1,
                "rules": [{"rule_id": "R-1", "title": "标题", "text": "正文。"}],
            }
        )


def test_a_served_bundle_with_a_bad_manifest_hash_is_refused() -> None:
    with pytest.raises(ValueError, match="manifest_hash"):
        served_bundle_of(
            {
                "bundle_id": "policy-x",
                "merchant_id": "M-1001",
                "version": "2026.09",
                "manifest_hash": "not-a-digest",
                "safety_epoch": 1,
                "rules": [{"rule_id": "R-1", "title": "标题", "text": "正文。"}],
            }
        )


class _StubForDense:
    """A dense embedder for the plumbing tests, with the two misbehaviours worth excluding made reachable."""

    def __init__(
        self,
        *,
        return_count: int | None = None,
        declared_dimension: int = 8,
        actual_dimension: int | None = None,
    ) -> None:
        self.model = "stub-embedder"
        self.revision = "stub-revision-1"
        self.dimension = declared_dimension
        self._return_count = return_count
        self._actual_dimension = actual_dimension if actual_dimension is not None else declared_dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        count = self._return_count if self._return_count is not None else len(texts)
        return [[0.5] * self._actual_dimension for _ in range(count)]
