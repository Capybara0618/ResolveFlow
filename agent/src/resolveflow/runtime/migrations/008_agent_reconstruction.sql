ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS request_body jsonb;
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS replay_spend jsonb;
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS sdk_state jsonb;
ALTER TABLE agent_run_model_budget ADD COLUMN IF NOT EXISTS manifest jsonb;
CREATE TABLE IF NOT EXISTS agent_tool_call (
    run_id uuid NOT NULL REFERENCES agent_run(run_id),
    call_id text NOT NULL,
    request_hash text NOT NULL,
    local_read boolean NOT NULL,
    observation jsonb,
    attempts integer NOT NULL DEFAULT 1,
    PRIMARY KEY(run_id,call_id)
);
