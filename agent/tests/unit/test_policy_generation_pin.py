from types import SimpleNamespace

from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.policies.index import PolicyIndex


def runner(generations):
    index = PolicyIndex(None)
    index.generation_for = lambda bundle, manifest: (
        SimpleNamespace(generation_id=generations[bundle]) if bundle in generations else None
    )
    facts = SimpleNamespace(policy_manifest={"bundle_ids": ["b", "a"], "manifest_hash": "m"})
    return AgentScopeRunner(model=None, tools=None, facts=facts, policy_index=index)


def test_run_pins_all_generations_and_never_refreshes_during_investigation():
    generations = {"a": "old-a", "b": "old-b"}
    run = runner(generations)
    identity = run.index_generation()
    generations["b"] = "new-b"
    assert run.index_generation() == identity
    assert run._selected_policy_generations == {"a": "old-a", "b": "old-b"}
    assert runner(generations).index_generation() != identity


def test_missing_ready_generation_is_frozen_without_late_substitution():
    generations = {"a": "old-a"}
    run = runner(generations)
    identity = run.index_generation()
    generations["b"] = "late-b"
    assert run.index_generation() == identity
    assert run._selected_policy_generations == {"a": "old-a"}
    assert runner(generations).index_generation() != identity
