ALTER TABLE agent_model_call ADD COLUMN IF NOT EXISTS settled_spend jsonb;
ALTER TABLE agent_tool_call ADD COLUMN IF NOT EXISTS before_spend jsonb;
ALTER TABLE agent_tool_call ADD COLUMN IF NOT EXISTS after_spend jsonb;
