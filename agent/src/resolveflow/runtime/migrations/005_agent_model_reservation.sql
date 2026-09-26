-- C09 first durable slice: frozen budget partition and pre-network model-call reservation.
-- This does not enable recovery scheduling or migrate old RUNNING investigations.
CREATE TABLE IF NOT EXISTS agent_run_model_budget (
    run_id uuid PRIMARY KEY REFERENCES agent_run(run_id),
    manifest_id text NOT NULL,
    budget jsonb NOT NULL,
    call_partition jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_model_call (
    run_id uuid NOT NULL REFERENCES agent_run(run_id),
    call_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('ORDINARY', 'RECOVERY_TURN')),
    request_hash text NOT NULL,
    reserved_input bigint NOT NULL CHECK (reserved_input >= 0),
    reserved_output bigint NOT NULL CHECK (reserved_output > 0),
    -- No response saved in this slice: UNKNOWN retains the full conservative reservation.
    state text NOT NULL CHECK (state IN ('UNKNOWN', 'SAVED')),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (run_id, call_id)
);
