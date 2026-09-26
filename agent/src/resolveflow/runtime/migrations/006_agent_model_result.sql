-- C09 saved explicit model replies and once-only usage settlement, append-only.
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS response jsonb;
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS saved_at timestamptz;
ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS stop_reason text;
ALTER TABLE agent_run_model_budget ADD COLUMN IF NOT EXISTS stop_reason text;
