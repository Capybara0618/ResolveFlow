-- C06.1b — the callback outbox (docs/domain-model.md:69, docs/core-contracts.md:59).
--
-- Why a table and not a direct HTTP call: a callback is a decision the Agent has already made. If
-- delivery were the only record of it, a connection refused at the wrong moment would erase a fact that
-- the run really reached — and the case would sit in ANALYZING forever with nothing to explain why. So the
-- row is written first, in the same transaction as the change that produced it, and delivery is a
-- retryable consequence of the row (docs/agent-harness.md:27 — 外部网络调用不放长事务).
--
-- Append-only: 001_agent_run.sql has already run against a database, so this is a new file rather than an
-- edit. The next change to *these* tables is another new file.

CREATE TABLE IF NOT EXISTS agent_callback_outbox (
    -- The idempotency key, and the primary key: a redelivery after a lost acknowledgement has to be
    -- recognisably the same callback, which is only possible if the id is derived rather than random
    -- (contracts/core/openapi-case.yaml:2207).
    callback_id           text        PRIMARY KEY,
    run_id                uuid        NOT NULL REFERENCES agent_run (run_id),
    case_id               uuid        NOT NULL,
    input_revision        integer     NOT NULL,

    kind                  text        NOT NULL CHECK (kind IN ('STARTED', 'QUESTION', 'PROPOSAL', 'FAILED')),

    -- The payload as it will be sent. jsonb rather than columns per kind: the four payload shapes are
    -- defined by the case contract and validated in Python before the row is written
    -- (agent/src/resolveflow/runtime/callbacks.py), so the database stores the envelope it will transmit
    -- rather than a second, divergent copy of the schema.
    payload               jsonb       NOT NULL,

    traceparent           text,

    -- PENDING means "not yet accepted by the case service". DELIVERED means the case service answered,
    -- whichever answer it gave: ACCEPTED and DUPLICATE both mean it has the callback, and STALE means it
    -- can no longer be applied to any revision — none of the three is work to retry
    -- (contracts/core/openapi-case.yaml:1284).
    status                text        NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DELIVERED')),
    attempts              integer     NOT NULL DEFAULT 0,

    -- What the case service finally said: ACCEPTED, DUPLICATE or STALE. NULL until it answers, so a
    -- reader can tell "not yet answered" from "answered".
    disposition           text,

    -- The last failure, kept rather than cleared: a delivery that only ever succeeded on the tenth attempt
    -- should be able to say what the first nine saw.
    last_error            text,

    -- When to try again. Set on failure; NULL on a fresh row, which means "due now".
    next_attempt_at       timestamptz,

    created_at            timestamptz NOT NULL,
    updated_at            timestamptz NOT NULL,
    delivered_at          timestamptz
);

-- How the delivery loop finds work: due first, oldest first, so a backlog ages visibly instead of being
-- sampled at random. Partial, because DELIVERED rows are history and never drained.
CREATE INDEX IF NOT EXISTS agent_callback_outbox_pending_idx
    ON agent_callback_outbox (next_attempt_at, created_at)
    WHERE status = 'PENDING';

-- What RunView.callback_ids reports, and what a reader asks to see the callbacks of one run.
CREATE INDEX IF NOT EXISTS agent_callback_outbox_run_idx ON agent_callback_outbox (run_id, created_at);