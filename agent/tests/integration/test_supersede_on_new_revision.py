"""C08.2 — 补证：a newer revision of a case makes the older run's unfinished result inapplicable.

``docs/agent-spec.md:9``: 补证创建新revision/new run，旧run STALE，且新run重新取得物流/退款/政策有效事实.
``docs/agentscope-migration.md:68`` requires the run status and the callback outbox to commit together, which is why
the supersession happens inside the new dispatch's own transaction and why the superseded run's undelivered
callbacks are closed at the same moment.

The last test here is the point of the whole mechanism: a run that is superseded while it is still investigating
cannot file the result it was about to file, because that result is about a revision the case has moved past.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from resolveflow.harness.actions import validate_decision
from resolveflow.harness.vocabulary import RunResult
from resolveflow.runtime.callbacks import CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller
from tests.integration import future_deadline
from resolveflow.runtime.worker import RunWorker

RUN_ID = "11111111-2222-4333-8444-555555555555"
SECOND_RUN_ID = "22222222-3333-4444-8555-666666666666"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)

NOW = dt.datetime(2026, 9, 26, 10, 0, tzinfo=dt.UTC)


def a_run(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "order_id": "00000000-0000-4000-8000-0000000000aa",
        "line_id": "7001",
        "description": "包裹损坏，希望退款",
        "requested_actions": ["REFUND"],
        "evidence_refs": ["ev-1"],
        "policy_manifest": {
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": "9" * 64,
            "safety_epoch": 1,
        },
        "deadline_at": future_deadline(),
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    fields.update(overrides)
    return RunRequest(**fields)


def supplementary(**overrides: Any) -> RunRequest:
    """The dispatch a case service sends after the customer supplies more evidence (US-C3)."""
    fields: dict[str, Any] = {
        "run_id": SECOND_RUN_ID,
        "input_revision": 2,
        "description": "包裹损坏，希望退款；客户补充了开箱照片",
        "evidence_refs": ["ev-1", "ev-2"],
    }
    fields.update(overrides)
    return a_run(**fields)


def proposal_result() -> RunResult:
    return RunResult(
        completed=True,
        reason_code="COMPLETED",
        decision=validate_decision(
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "REFUND",
                "reason_codes": ["DAMAGED"],
                "summary": "照片确认损坏",
            }
        ),
        observations=(),
        spend=object(),
    )


def worker_for(agent_db: Database, result: RunResult | None = None) -> RunWorker:
    def investigate(facts: Any) -> RunResult:
        assert result is not None, "this worker was not expected to investigate"
        return result

    return RunWorker(agent_db, investigate=investigate)


def status_of(agent_db: Database, run_id: str) -> str:
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT status FROM agent_run WHERE run_id = %(run_id)s", {"run_id": run_id}
        ).fetchone()
    assert row is not None
    return str(row["status"])


def test_a_new_revision_supersedes_the_older_revision_s_unfinished_run(agent_db: Database) -> None:
    """The older run's result can no longer be applied, so it is not left looking claimable."""
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)

    store.queue(supplementary(), caller=CASE_DISPATCHER)

    assert status_of(agent_db, RUN_ID) == "STALE"
    assert status_of(agent_db, SECOND_RUN_ID) == "QUEUED", "the new run is the one that will be investigated"


def test_the_superseded_run_s_undelivered_callbacks_are_closed_without_counting_an_attempt(
    agent_db: Database,
) -> None:
    """A question or proposal for a revision the case moved past must not be handed over at all.

    ``attempts`` is not incremented: it counts how many times the case service was called, and this callback was
    never sent. A voided callback that claimed an attempt would make a case service that was never asked look
    like one that refused.
    """
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    worker_for(agent_db).claim_one(now=NOW)  # the STARTED callback is filed and still pending

    store.queue(supplementary(), caller=CASE_DISPATCHER)

    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    assert [record.kind for record in records] == ["STARTED"]
    assert records[0].status == "DEAD"
    assert records[0].attempts == 0
    assert records[0].last_error == "SUPERSEDED_BY_REVISION:2"


def test_a_delivered_callback_keeps_the_answer_the_case_service_already_gave_it(
    agent_db: Database,
) -> None:
    """The case service's own answer is history; supersession must not rewrite it.

    ``contracts.md:80``: an answer of ACCEPTED/DUPLICATE means the case service has the callback. Relabelling that
    row as voided would hide that the case service was told something, which is the opposite of what an audit
    record of a delivery is for.
    """
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    worker_for(agent_db).claim_one(now=NOW)
    callbacks = CallbackStore(agent_db)
    started = callbacks.list_for_run(RUN_ID)[0]
    callbacks.record_delivery(started.callback_id, disposition="ACCEPTED")

    store.queue(supplementary(), caller=CASE_DISPATCHER)

    after = callbacks.list_for_run(RUN_ID)[0]
    assert (after.status, after.disposition) == ("DELIVERED", "ACCEPTED")
    assert after.last_error is None
    # The run itself is still superseded: the revision moved on, whatever the delivery did.
    assert status_of(agent_db, RUN_ID) == "STALE"


def test_a_superseded_run_is_never_investigated(agent_db: Database) -> None:
    """No budget is spent on a result that cannot be applied."""
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    store.queue(supplementary(), caller=CASE_DISPATCHER)

    claimed = worker_for(agent_db, proposal_result()).claim_one(now=NOW)

    assert claimed is not None
    assert claimed.facts.run_id == SECOND_RUN_ID, "the superseded run must not be the one picked up"
    assert CallbackStore(agent_db).list_for_run(RUN_ID) == [], "a run that never starts files no STARTED"


def test_a_run_superseded_mid_investigation_cannot_file_its_result(agent_db: Database) -> None:
    """US-C3's "旧结果不会覆盖", stated as the race it really is.

    The customer supplies evidence while the investigation is running. The result that investigation was about to
    file is about a revision the case has moved past, so it must not be filed — the run is already STALE and the
    worker's conditional update refuses. ``docs/agentscope-migration.md:68``: 补证new revision/new run与同run故障
    恢复严格分开 — this is the first, and no recovery machinery is involved in it.
    """
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    worker = worker_for(agent_db, proposal_result())
    claimed = worker.claim_one(now=NOW)
    assert claimed is not None
    store.queue(supplementary(), caller=CASE_DISPATCHER)

    outcome = worker.finish(claimed, proposal_result(), now=NOW)

    assert outcome.status == "STALE"
    assert outcome.callback_kind is None
    assert status_of(agent_db, RUN_ID) == "STALE"
    kinds = [record.kind for record in CallbackStore(agent_db).list_for_run(RUN_ID)]
    assert "PROPOSAL" not in kinds, kinds


def test_a_finished_run_is_not_relabelled_by_a_new_revision(agent_db: Database) -> None:
    """What already happened is not undone by what happens next.

    A ``COMPLETED`` run is one whose proposal callback the case service accepted (``docs/agent-spec.md:9``) — that
    acceptance is a fact about the past, and marking the run STALE would erase it. Whether the *proposal* is still
    applicable is the case service's own ``case_proposal`` row (``docs/domain-model.md:57``). A ``CANCELLED`` run
    likewise keeps its cancellation: it was withdrawn for its own reason, not superseded.
    """
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    # A second case, because one case and revision is one run (the unique index says so), and because a
    # cancellation is a different case's business.
    other_case = "44444444-5555-4666-8777-888888888888"
    cancelled_run = a_run(
        run_id="33333333-4444-4555-8666-777777777777", input_revision=1, case_id=other_case
    )
    store.queue(cancelled_run, caller=CASE_DISPATCHER)
    with agent_db.connection() as connection:
        connection.execute(
            "UPDATE agent_run SET status = 'COMPLETED' WHERE run_id = %(run_id)s", {"run_id": RUN_ID}
        )
        connection.execute(
            "UPDATE agent_run SET status = 'CANCELLED' WHERE run_id = %(run_id)s",
            {"run_id": cancelled_run.run_id},
        )

    store.queue(supplementary(), caller=CASE_DISPATCHER)

    assert status_of(agent_db, RUN_ID) == "COMPLETED"
    assert status_of(agent_db, cancelled_run.run_id) == "CANCELLED"


def test_the_new_run_reads_its_own_facts_and_inherits_nothing(agent_db: Database) -> None:
    """The new run re-acquires logistics/refund/policy facts rather than reusing the old run's.

    ``docs/agent-spec.md:9``: 新run可继承用户问答，但重新取得物流/退款/政策有效事实. The Q&A is the case service's
    (it re-dispatches with the answer in the description and evidence); what must **not** carry over is anything the
    agent observed — so the new run's own claim starts with the new revision, the new description and the new
    evidence, and with no observations at all.
    """
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    store.queue(supplementary(), caller=CASE_DISPATCHER)

    claimed = worker_for(agent_db, proposal_result()).claim_one(now=NOW)

    assert claimed is not None
    assert claimed.facts.input_revision == 2
    assert claimed.facts.description == "包裹损坏，希望退款；客户补充了开箱照片"
    assert claimed.case_id == CASE_ID
    assert claimed.facts.policy_manifest["bundle_ids"] == ["policy-logistics-2026.09"]