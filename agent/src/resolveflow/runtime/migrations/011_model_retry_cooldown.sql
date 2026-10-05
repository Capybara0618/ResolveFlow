-- Preserve rate-limit cooldown across worker restarts; never extend the run deadline.
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS model_retry_after timestamptz;
ALTER TABLE agent_model_attempt ADD COLUMN IF NOT EXISTS failure_code text;
ALTER TABLE agent_model_attempt ADD COLUMN IF NOT EXISTS retry_after_at timestamptz;
