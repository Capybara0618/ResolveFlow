"""Shared request ceilings and resumable execution metadata, with temporary ledgers only."""

import json

import pytest
from scripts.customer_harness_live_v1 import (
    CONTEXT_LIMIT,
    RECOVERY_LIMIT,
    TOTAL_LIMIT,
    context_slots,
    create_manifest,
    review_template,
    validate_prefix,
)
from scripts.evaluation.customer_harness_budget_v1 import BudgetSession, reserve

from resolveflow.support.protocol import SupportFailure


def ledger(tmp_path, used=17):
    path = tmp_path / 'usage.json'
    path.write_text(json.dumps({'used': used, 'historical_limit': 100, 'extra': {'keep': True}}), encoding='utf-8')
    return path


def test_one_total_and_per_phase_limit_shared_across_attachments_and_preserved_metadata(tmp_path):
    path = ledger(tmp_path)
    with BudgetSession(path, 'session-1', 'plan-sha', expected_start=17,
                       limits={'context': 2, 'recovery': 1}, total=3) as session:
        for phase in ('context', 'context', 'recovery'):
            reserve(path, session.session_id, session.token, phase)
        with pytest.raises(SupportFailure, match='EVALUATION_ALLOWANCE_EXHAUSTED'):
            reserve(path, session.session_id, session.token, 'recovery')
    value = json.loads(path.read_text(encoding='utf-8'))
    assert value['used'] == 20 and value['extra'] == {'keep': True} and value['historical_limit'] == 100
    assert value['hctx_sessions']['session-1']['used_by_phase'] == {'context': 2, 'recovery': 1}
    assert not path.with_name(path.name + '.lock').exists()


def test_reopening_session_keeps_original_start_and_consumed_budget(tmp_path):
    path = ledger(tmp_path)
    with BudgetSession(path, 'same', 'plan', expected_start=17, limits={'context': 2}, total=2) as first:
        reserve(path, first.session_id, first.token, 'context')
    with BudgetSession(path, 'same', 'plan', expected_start=17, limits={'context': 2}, total=2) as second:
        reserve(path, second.session_id, second.token, 'context')
        with pytest.raises(SupportFailure, match='EVALUATION_ALLOWANCE_EXHAUSTED'):
            reserve(path, second.session_id, second.token, 'context')
    assert json.loads(path.read_text(encoding='utf-8'))['used'] == 19


def test_wrong_owner_plan_start_and_parallel_session_do_not_reset_ledger(tmp_path):
    path = ledger(tmp_path)
    with pytest.raises(ValueError, match='start'):
        with BudgetSession(path, 'wrong', 'plan', expected_start=16, limits={'context': 2}, total=2):
            pass
    assert json.loads(path.read_text(encoding='utf-8'))['used'] == 17
    with BudgetSession(path, 'same', 'plan', expected_start=17, limits={'context': 2}, total=2) as session:
        with pytest.raises(ValueError, match='locked'):
            with BudgetSession(path, 'parallel', 'plan', expected_start=17, limits={'context': 2}, total=2):
                pass
        with pytest.raises(ValueError, match='owner'):
            reserve(path, session.session_id, 'foreign-token', 'context')
    with pytest.raises(ValueError, match='immutable'):
        with BudgetSession(path, 'same', 'other-plan', expected_start=17, limits={'context': 2}, total=2):
            pass


def test_preexisting_unknown_lock_is_not_removed(tmp_path):
    path = ledger(tmp_path)
    lock = path.with_name(path.name + '.lock')
    lock.write_text('123456789', encoding='utf-8')
    with pytest.raises(ValueError, match='locked'):
        with BudgetSession(path, 'new', 'plan', expected_start=17, limits={'context': 1}, total=1):
            pass
    assert lock.read_text(encoding='utf-8') == '123456789'


def test_reservation_is_persisted_before_any_model_send_and_counts_even_if_no_response(tmp_path):
    path = ledger(tmp_path)
    with BudgetSession(path, 's', 'plan', expected_start=17, limits={'context': 1}, total=1) as session:
        reserve(path, session.session_id, session.token, 'context')
        # A crash after reserve must not refund or silently retry this allowance.
    assert json.loads(path.read_text(encoding='utf-8'))['used'] == 18
    with pytest.raises(ValueError, match='active owner'):
        reserve(path, session.session_id, session.token, 'context')


def test_frozen_plan_and_review_have_no_quality_claims_or_credentials():
    plan = create_manifest()
    assert TOTAL_LIMIT == CONTEXT_LIMIT + RECOVERY_LIMIT == 700
    assert plan['context_turns'] == 64 and plan['recovery_pairs'] == 15
    assert plan['limits'] == {'context': 400, 'recovery': 300}
    assert plan['total_requests'] == 700
    review = review_template()
    assert len(review['context']) == 64
    assert all(r['pass'] is None for r in review['context'])
    assert 'api_key' not in json.dumps(plan) and 'token' not in json.dumps(plan.get('credentials', {}))


def test_completed_context_prefix_is_reused_but_foreign_or_inflight_prefix_is_rejected():
    slots = context_slots()
    assert len(slots) == 64 and len({(s['case_id'], s['variant'], s['checkpoint']) for s in slots}) == 64
    row = dict(slots[0], state='COMPLETE', result={'status': 'FAILED', 'answer': None}, models=[])
    assert validate_prefix([row], slots) == 1
    with pytest.raises(ValueError, match='prefix'):
        validate_prefix([{**row, 'case_id': 'foreign'}], slots)
    with pytest.raises(ValueError, match='in-flight'):
        validate_prefix([{**row, 'state': 'STARTED'}], slots)


def test_manifest_binds_new_entrypoint_and_old_preparation_without_rewriting_it():
    plan = create_manifest()
    for name in ('scripts/customer_harness_live_v1.py', 'scripts/evaluation/customer_harness_budget_v1.py',
                 'evals/customer-harness-context-v1/cases.json',
                 'reports/customer-harness-context-v1/preparation.json'):
        assert name in plan['files']
    assert all(len(h) == 64 for h in plan['files'].values())


def test_write_failure_never_causes_an_in_memory_refund(tmp_path, monkeypatch):
    from scripts.evaluation import customer_harness_budget_v1 as budget
    path = ledger(tmp_path)
    with BudgetSession(path, 's', 'plan', expected_start=17, limits={'context': 1}, total=1) as session:
        def fail(*args):
            raise PermissionError('synthetic ledger I/O error')
        with monkeypatch.context() as changes:
            changes.setattr(budget, 'persist', fail)
            with pytest.raises(PermissionError):
                reserve(path, session.session_id, session.token, 'context')
    assert json.loads(path.read_text(encoding='utf-8'))['used'] == 17
