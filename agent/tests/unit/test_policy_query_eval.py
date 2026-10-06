"""Failure tests for frozen scope, source-span scoring and honest review gates."""

import copy
import json

import pytest
from scripts.policy_query_eval import coverage, rank, score_row, validate_cases


def fixture():
    atoms = {"a": {"source_id": "s", "raw_sha256": "v1", "block_id": "b", "table_row": None, "text_range": [2, 8]}}
    chunks = [
        {
            "id": "c1",
            "source_id": "s",
            "raw_sha256": "v1",
            "subject": "EXTERNAL:T",
            "retrieval_text": "refund",
            "embedding": [1.0, 0.0],
            "context_id": "ctx",
            "fragments": [{"block_id": "b", "text_range": [0, 5], "text": "12345"}],
        },
        {
            "id": "c2",
            "source_id": "s",
            "raw_sha256": "v1",
            "subject": "EXTERNAL:T",
            "retrieval_text": "policy",
            "embedding": [0.0, 1.0],
            "context_id": "ctx",
            "fragments": [{"block_id": "b", "text_range": [5, 10], "text": "67890"}],
        },
    ]
    from scripts.policy_documents import digest

    bundle = {
        "chunks": chunks,
        "contexts": {
            "ctx": {
                "source_id": "s",
                "raw_sha256": "v1",
                "subject": "EXTERNAL:T",
                "required_block_ids": ["b"],
                "text": "1234567890",
                "text_sha256": digest(b"1234567890"),
            }
        },
    }
    case = {
        "id": "q",
        "query": "refund",
        "subject": "EXTERNAL:T",
        "scope": [{"source_id": "s", "raw_sha256": "v1"}],
        "origin": {"kind": "CODEX_SYNTHETIC"},
        "draft": {
            "answerability": "ANSWERABLE",
            "required": ["a"],
            "related_not_sufficient": [],
            "rationale": "source annotation",
        },
        "review": {"state": "PENDING", "reviewer": None, "origin": None, "labels": None},
    }
    return case, bundle, atoms


def test_partial_fragment_is_not_full_evidence_and_union_can_complete_it():
    _, bundle, atoms = fixture()
    assert coverage(bundle["chunks"][:1], atoms["a"]) is False
    assert coverage(bundle["chunks"], atoms["a"]) is True


def test_duplicate_overlap_does_not_fill_a_gap():
    _, bundle, atoms = fixture()
    assert coverage([bundle["chunks"][0]] * 2, atoms["a"]) is False


@pytest.mark.parametrize("field,value", [("raw_sha256", "v2"), ("source_id", "other")])
def test_wrong_snapshot_or_source_cannot_cover_evidence(field, value):
    _, bundle, atoms = fixture()
    bad = copy.deepcopy(bundle["chunks"])
    for c in bad:
        c[field] = value
    assert not coverage(bad, atoms["a"])


def test_scope_filters_before_ranking_for_dense_and_lexical():
    case, bundle, _ = fixture()
    outsider = copy.deepcopy(bundle["chunks"][0])
    outsider["id"] = "outside"
    outsider["source_id"] = "other"
    outsider["retrieval_text"] = "refund " * 10
    old = copy.deepcopy(bundle["chunks"][0])
    old["id"] = "old"
    old["raw_sha256"] = "v0"
    bundle["chunks"] += [outsider, old]
    for method in ("dense", "bm25"):
        assert {c["id"] for c, _ in rank(case, bundle, method, [1.0, 0.0])} == {"c1", "c2"}


def test_context_expansion_is_deduplicated_and_pending_is_unscored():
    case, bundle, atoms = fixture()
    row = score_row(case, [(c, 1.0) for c in bundle["chunks"]], bundle, atoms, 100)
    assert row["official_score"] is None
    assert row["at_k"]["2"]["exported_chars"] == 10
    assert row["at_k"]["2"]["draft_context_complete"] is True


def test_budget_refusal_does_not_count_as_delivered_context():
    case, bundle, atoms = fixture()
    row = score_row(case, [(bundle["chunks"][0], 1.0)], bundle, atoms, 5)
    assert row["at_k"]["2"]["draft_context_complete"] is False
    assert row["at_k"]["2"]["blocked_context_ids"] == ["ctx"]
    assert row["at_k"]["2"]["exported_chars"] == 0


def test_no_answer_does_not_pass_vacuously():
    case, bundle, atoms = fixture()
    case["draft"] |= {"answerability": "NOT_IN_CORPUS", "required": []}
    row = score_row(case, [(c, 1.0) for c in bundle["chunks"]], bundle, atoms, 100)
    assert row["at_k"]["2"]["draft_direct_complete"] is None
    assert row["official_score"] is None


@pytest.mark.parametrize("mutation", ["missing_atom", "wrong_scope", "fake_review", "duplicate_id", "pending_gold"])
def test_invalid_annotations_fail_closed(mutation):
    case, _, atoms = fixture()
    cases = [case]
    if mutation == "missing_atom":
        case["draft"]["required"] = ["unknown"]
    if mutation == "wrong_scope":
        case["scope"][0]["raw_sha256"] = "v2"
    if mutation == "fake_review":
        case["review"]["state"] = "APPROVED"
    if mutation == "duplicate_id":
        cases.append(copy.deepcopy(case))
    if mutation == "pending_gold":
        case["review"]["labels"] = copy.deepcopy(case["draft"])
    with pytest.raises(ValueError):
        validate_cases(cases, atoms)


def test_independent_review_scores_its_own_labels_not_draft():
    case, bundle, atoms = fixture()
    labels = copy.deepcopy(case["draft"])
    labels["required"] = ["other"]
    atoms["other"] = atoms["a"] | {"text_range": [0, 4]}
    case["review"] = {
        "state": "APPROVED",
        "reviewer": "fixture-independent-human",
        "origin": "INDEPENDENT_HUMAN",
        "labels": labels,
    }
    validate_cases([case], atoms)
    row = score_row(case, [(bundle["chunks"][0], 1.0)], bundle, atoms, 100)
    assert row["at_k"]["2"]["draft_direct_complete"] is False
    assert row["at_k"]["2"]["reviewed_direct_complete"] is True
    assert row["official_score"]["2"] is True


def test_whole_span_match_in_another_table_row_is_not_evidence():
    _, bundle, atoms = fixture()
    atoms["a"]["table_row"] = 1
    assert not coverage(bundle["chunks"], atoms["a"])


def test_scope_violation_cannot_reach_scorer():
    case, bundle, atoms = fixture()
    bundle["chunks"][0]["subject"] = "EXTERNAL:OTHER"
    with pytest.raises(ValueError, match="scope"):
        score_row(case, [(bundle["chunks"][0], 1.0)], bundle, atoms, 100)


def test_total_budget_includes_all_contexts_and_separator():
    case, bundle, atoms = fixture()
    from scripts.policy_documents import digest

    second = copy.deepcopy(bundle["contexts"]["ctx"])
    second.update(text="abcde", text_sha256=digest(b"abcde"))
    bundle["contexts"]["ctx2"] = second
    bundle["chunks"][1]["context_id"] = "ctx2"
    ranked = [(c, 1.0) for c in bundle["chunks"]]
    row = score_row(case, ranked, bundle, atoms, 16)
    assert row["at_k"]["2"]["exported_chars"] == 10
    assert row["at_k"]["2"]["blocked_context_ids"] == ["ctx2"]
    row = score_row(case, ranked, bundle, atoms, 17)
    assert row["at_k"]["2"]["exported_chars"] == 17


def test_identical_payload_with_different_context_ids_is_not_counted_twice():
    case, bundle, atoms = fixture()
    bundle["contexts"]["alias"] = copy.deepcopy(bundle["contexts"]["ctx"])
    bundle["chunks"][1]["context_id"] = "alias"
    row = score_row(case, [(c, 1.0) for c in bundle["chunks"]], bundle, atoms, 100)
    assert row["at_k"]["2"]["exported_chars"] == 10


def frozen_inputs(tmp_path, monkeypatch):
    import scripts.policy_query_eval as module
    from scripts.policy_documents import digest

    monkeypatch.setattr(module, "ROOT", tmp_path)
    case, children, atoms = fixture()
    block = {"id": "b", "kind": "paragraph", "text": "1234567890", "text_sha256": digest(b"1234567890")}
    doc = {
        "source_id": "s",
        "subject": "EXTERNAL:T",
        "raw_sha256": "v1",
        "blocks": [block],
        "source_url": "https://example.org/policy",
    }
    draft = {"documents": [doc]}

    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    upstream = tmp_path / "evals/external-faq-v1"
    for name in ("queries.json", "sources.json"):
        write(upstream / name, [])
    write(
        upstream / "manifest.json",
        {"files": {name: digest((upstream / name).read_bytes()) for name in ("queries.json", "sources.json")}},
    )
    code = tmp_path / "scripts/policy_chunks.py"
    write(code, "fixture")
    draft_path = tmp_path / "draft.json"
    write(draft_path, draft)
    children.update(builder_sha256=digest(code.read_bytes()), source_draft_sha256=digest(draft_path.read_bytes()))
    child_path = tmp_path / "child.json"
    write(child_path, children)
    atoms["a"].update(
        id="a",
        subject="EXTERNAL:T",
        block_text_sha256=block["text_sha256"],
        representation_sha256=digest(b"1234567890"),
        span_sha256=digest(b"345678"),
    )
    directory = tmp_path / "dataset"
    write(directory / "queries.json", [case])
    write(directory / "evidence.json", list(atoms.values()))
    manifest = {
        "files": {name: digest((directory / name).read_bytes()) for name in ("queries.json", "evidence.json")},
        "children_sha256": digest(child_path.read_bytes()),
        "draft_sha256": digest(draft_path.read_bytes()),
        "faq_manifest_sha256": digest((upstream / "manifest.json").read_bytes()),
        "queries": 1,
        "faq_questions": 0,
        "synthetic_questions": 1,
        "source_families": 1,
    }
    write(directory / "manifest.json", manifest)
    monkeypatch.setattr(module, "load_draft", lambda *_: draft)
    return module, directory, child_path, draft_path, write


@pytest.mark.parametrize("mutation", [None, "file_drift", "span_hash", "wrong_subject", "denominator"])
def test_frozen_loader_rejects_drift_and_source_annotation_errors(tmp_path, monkeypatch, mutation):
    module, directory, child_path, draft_path, write = frozen_inputs(tmp_path, monkeypatch)
    from scripts.policy_documents import digest

    if mutation == "file_drift":
        (directory / "queries.json").write_text("[]", encoding="utf-8")
    elif mutation in ("span_hash", "wrong_subject"):
        atoms = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
        atoms[0]["span_sha256" if mutation == "span_hash" else "subject"] = "wrong"
        write(directory / "evidence.json", atoms)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["evidence.json"] = digest((directory / "evidence.json").read_bytes())
        write(directory / "manifest.json", manifest)
    elif mutation == "denominator":
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest["queries"] = 2
        write(directory / "manifest.json", manifest)
    if mutation:
        with pytest.raises(ValueError):
            module.load_inputs(directory, child_path, draft_path)
    else:
        assert len(module.load_inputs(directory, child_path, draft_path)[1]) == 1


def test_review_pack_has_all_sources_but_no_draft_labels_or_ranking(tmp_path, monkeypatch, capsys):
    module, directory, child_path, draft_path, _ = frozen_inputs(tmp_path, monkeypatch)
    output = tmp_path / "tmp/review.json"
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "eval",
            "--dataset",
            str(directory),
            "--children",
            str(child_path),
            "--draft",
            str(draft_path),
            "--prepare-review",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(module, "embedder", lambda: pytest.fail("review mode must not call model"))
    module.main()
    pack = json.loads(output.read_text(encoding="utf-8"))
    assert "draft" not in pack["questions"][0] and "review" not in pack["questions"][0]
    assert pack["documents"][0]["blocks"][0]["text"] == "1234567890"
    assert json.loads(capsys.readouterr().out)["rankings"] == 0


def test_review_gate_refuses_pending_without_creating_report(tmp_path, monkeypatch):
    module, directory, child_path, draft_path, _ = frozen_inputs(tmp_path, monkeypatch)
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "eval",
            "--dataset",
            str(directory),
            "--children",
            str(child_path),
            "--draft",
            str(draft_path),
            "--require-reviewed",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(module, "embedder", lambda: pytest.fail("gate must reject before model"))
    with pytest.raises(ValueError, match="pending"):
        module.main()
    assert not output.exists()


def test_full_source_review_pack_cannot_export_outside_ignored_tmp(tmp_path, monkeypatch):
    module, directory, child_path, draft_path, _ = frozen_inputs(tmp_path, monkeypatch)
    output = tmp_path / "reports/full-sources.json"
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "eval",
            "--dataset",
            str(directory),
            "--children",
            str(child_path),
            "--draft",
            str(draft_path),
            "--prepare-review",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(ValueError, match="ignored local tmp"):
        module.main()
    assert not output.exists()


def test_existing_report_is_never_overwritten(tmp_path, monkeypatch):
    module, directory, child_path, draft_path, _ = frozen_inputs(tmp_path, monkeypatch)
    output = tmp_path / "result.json"
    output.write_text("old report", encoding="utf-8")
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "eval",
            "--dataset",
            str(directory),
            "--children",
            str(child_path),
            "--draft",
            str(draft_path),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(FileExistsError):
        module.main()
    assert output.read_text(encoding="utf-8") == "old report"
