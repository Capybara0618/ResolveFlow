-- C06.1c — the run binding: which run belongs to which case revision (docs/domain-model.md:28).
--
-- Why a table rather than a column on aftersale_case: the binding is per (case_id, input_revision), and a
-- case gains revisions. One column would have to be overwritten as the case moves, which would erase the
-- record of the run that decided the *previous* revision — the run whose proposal, callback and cost still
-- exist in the Agent's database. A row per revision is the same shape the Agent uses on its side.
--
-- Why the row is written with the case and not after it: docs/domain-model.md:45 puts an outbox row in the
-- transaction that decided it. A case committed without a binding is a case nothing will investigate, and
-- no later read can tell whether it was forgotten or never meant to have a run. The dispatch (a network
-- call) then happens outside the transaction, driven by dispatch_status.
--
-- Migrations are append-only (docs/engineering.md:64): this file is never edited after it has run.

CREATE TABLE agent_binding (
    case_id         CHAR(36)    NOT NULL,
    -- The decision-input revision, not an optimistic-lock version (contracts/core/openapi-agent.yaml:320).
    input_revision  INT         NOT NULL,
    -- The run this revision is investigated by. Derived from (case_id, input_revision), so a retry
    -- recomputes the same id and the Agent's idempotent intake answers for the row it already has.
    run_id          CHAR(36)    NOT NULL,
    -- PENDING until the Agent has accepted the run (its 202). An outage leaves it PENDING: a run that was
    -- never accepted must not be recorded as queued, or the case would wait forever for an Agent that
    -- never heard of it.
    dispatch_status VARCHAR(16) NOT NULL,
    created_at      DATETIME(6) NOT NULL,
    dispatched_at   DATETIME(6) NULL,
    PRIMARY KEY (case_id, input_revision),
    -- One run belongs to one case revision. The unique key is what makes the derivation safe and what
    -- makes a second dispatch of the same revision visible rather than silent.
    UNIQUE KEY uq_binding_run (run_id),
    -- How the dispatch loop finds work: oldest waiting first, so a backlog ages visibly rather than being
    -- sampled at random (the same shape as idx_case_merchant).
    KEY idx_binding_pending (dispatch_status, created_at, case_id),
    CONSTRAINT fk_binding_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT chk_binding_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_binding_status CHECK (dispatch_status IN ('PENDING', 'DISPATCHED')),
    -- A dispatched row has a time and a pending one does not: the two facts cannot disagree.
    CONSTRAINT chk_binding_dispatched_at CHECK (
        (dispatch_status = 'DISPATCHED' AND dispatched_at IS NOT NULL)
        OR (dispatch_status = 'PENDING' AND dispatched_at IS NULL))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;