-- C06.1 — the Agent's durable run records (docs/domain-model.md:63, docs/core-contracts.md:38).
--
-- Only the part of agent_db that C06.1 makes real is here. The LangGraph checkpoint tables are
-- created by LangGraph's own idempotent `setup()` (they belong to the graph library, not to this
-- repository), and model_call / tool_observation / context_snapshot / harness_manifest /
-- policy_generation arrive with the slices that write them. Columns that are deliberately ahead of
-- their writers are called out below rather than left to look used.
--
-- Append-only: this file has never run against any database (C06.1 is its first use), so it is
-- correctable in place until then. Once it has run anywhere, the next change is a new file.

CREATE TABLE IF NOT EXISTS agent_run (
    run_id                uuid        PRIMARY KEY,
    case_id               uuid        NOT NULL,
    input_revision        integer     NOT NULL,
    parent_run_id         uuid        REFERENCES agent_run (run_id),

    -- The subject the run was opened for. These are copied from the dispatched body, which case-service
    -- filled from the verified principal: a run that cannot say whose line it is investigating could not
    -- be re-checked by anyone.
    merchant_id           text        NOT NULL,
    customer_id           text        NOT NULL,
    order_id              uuid        NOT NULL,
    line_id               text        NOT NULL,

    -- The request as it arrived, hashed canonically. The hash is what makes "same run key, different
    -- body" a 409 instead of a silent overwrite (contracts/core/openapi-agent.yaml:60).
    request_hash          text        NOT NULL,
    request_description   text        NOT NULL,
    requested_actions     text[]      NOT NULL,
    evidence_refs         text[]      NOT NULL DEFAULT '{}',
    policy_manifest       jsonb       NOT NULL,
    traceparent           text,

    status                text        NOT NULL,
    version               bigint      NOT NULL DEFAULT 1,

    -- RunView.result_summary: a masked summary only, never raw model text
    -- (contracts/core/openapi-agent.yaml:515). Nothing produces one before the model client exists
    -- (C06.3), so it is NULL and the view says so rather than inventing a placeholder.
    result_summary        text,

    -- The queued deadline. Recovery must not extend it (docs/agent-spec.md:42), so it is stored at
    -- accept time and never recomputed. active_deadline_at is the window actually granted once a worker
    -- starts (docs/agent-spec.md:42); no worker exists yet, so nothing writes it in C06.1 and it stays
    -- NULL rather than being filled with a copy of deadline_at, which would read as "already started".
    deadline_at           timestamptz NOT NULL,
    active_deadline_at    timestamptz,

    -- Left NULL by this slice on purpose: leases and fences are how a worker is fenced (C09), and writing
    -- a fake lease here would claim an owner that does not exist.
    lease_owner           text,
    lease_until           timestamptz,
    fence                 bigint,

    -- usage accounting (docs/domain-model.md:63). Nothing spends budget before the model client exists
    -- (C06.3), so the counter starts at zero and a zero counter is the truthful value, not a placeholder.
    budget_spent          jsonb       NOT NULL DEFAULT '{}'::jsonb,

    created_at            timestamptz NOT NULL,
    updated_at            timestamptz NOT NULL,
    cancelled_at          timestamptz
);

-- The same case and revision are one run (docs/core-contracts.md:38: "同case/revision唯一"). case-service
-- derives run_id from the pair, and this index is the database's own statement of the same rule: two
-- dispatchers racing cannot both open a run for one revision.
CREATE UNIQUE INDEX IF NOT EXISTS agent_run_case_revision_idx ON agent_run (case_id, input_revision);

-- The order a durable queue is drained in: oldest queued run first, so a backlog is visible as an age
-- rather than as an arbitrary pick.
CREATE INDEX IF NOT EXISTS agent_run_queue_idx ON agent_run (status, created_at);