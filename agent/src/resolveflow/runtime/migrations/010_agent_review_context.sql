-- Case owns these immutable revision-bound inputs; the run stores exactly what was dispatched.
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS review_context JSONB NOT NULL DEFAULT '{}'::jsonb;
