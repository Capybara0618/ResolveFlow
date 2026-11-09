ALTER TABLE support_agent_call DROP CONSTRAINT support_agent_call_kind_with_jev_check;
ALTER TABLE support_agent_call ADD CONSTRAINT support_agent_call_kind_with_compaction_check
    CHECK (kind IN ('model', 'tool', 'jev', 'compaction'));
