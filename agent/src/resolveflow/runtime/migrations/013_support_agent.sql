-- Consultation runs own no Case/refund identity. No existing migration or runtime row is modified.
CREATE TABLE IF NOT EXISTS support_agent_run (
    run_id uuid PRIMARY KEY,
    input_json jsonb NOT NULL,
    manifest_json jsonb NOT NULL,
    status text NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED')),
    deadline_at timestamptz NOT NULL,
    lease_until timestamptz NOT NULL,
    fence bigint NOT NULL DEFAULT 1,
    spend_json jsonb NOT NULL DEFAULT '{}',
    generations_json jsonb NULL,
    result_json jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_agent_call (
    run_id uuid NOT NULL REFERENCES support_agent_run(run_id),
    kind text NOT NULL CHECK(kind IN ('model','tool')),
    position integer NOT NULL CHECK(position>0),
    request_hash text NOT NULL,
    request_json jsonb NOT NULL,
    status text NOT NULL CHECK(status IN ('STARTED','COMPLETE')),
    response_json jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id,kind,position)
);
