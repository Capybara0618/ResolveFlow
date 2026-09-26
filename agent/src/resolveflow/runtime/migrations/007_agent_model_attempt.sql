-- One logical call, at most the original transmission plus one retry.
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS current_attempt integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS agent_model_attempt (
    run_id uuid NOT NULL,
    call_id text NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no IN (0,1)),
    -- NULL for legacy rows: original ownership cannot be reconstructed from today's run fence.
    reserved_fence bigint,
    reserved_input bigint NOT NULL CHECK (reserved_input >= 0),
    reserved_output bigint NOT NULL CHECK (reserved_output > 0),
    state text NOT NULL CHECK (state IN ('UNKNOWN','SAVED')),
    response jsonb,
    saved_at timestamptz,
    stop_reason text,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (run_id,call_id,attempt_no),
    FOREIGN KEY (run_id,call_id) REFERENCES agent_model_call(run_id,call_id)
);
-- Preserve previously charged records without recharging or inventing their original fence.
INSERT INTO agent_model_attempt(run_id,call_id,attempt_no,reserved_input,reserved_output,state,
                                response,saved_at,stop_reason,created_at)
SELECT run_id,call_id,0,reserved_input,reserved_output,state,response,saved_at,stop_reason,created_at
FROM agent_model_call
ON CONFLICT (run_id,call_id,attempt_no) DO NOTHING;
