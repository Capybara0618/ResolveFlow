-- Separate typed audit records from generative model decisions; keep existing rows and wire protocols.
ALTER TABLE support_agent_call DROP CONSTRAINT IF EXISTS support_agent_call_kind_check;
ALTER TABLE support_agent_call DROP CONSTRAINT IF EXISTS support_agent_call_kind_with_jev_check;
ALTER TABLE support_agent_call ADD CONSTRAINT support_agent_call_kind_with_jev_check
    CHECK(kind IN ('model','tool','jev'));
