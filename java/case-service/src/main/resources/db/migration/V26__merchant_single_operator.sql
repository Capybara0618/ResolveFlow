-- Existing multi-person identities remain compatible; new platform merchants opt in explicitly.
ALTER TABLE identity_merchant ADD COLUMN single_operator BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE case_collaboration_event DROP CHECK ck_collaboration_action;
ALTER TABLE case_collaboration_event ADD CONSTRAINT ck_collaboration_action
    CHECK (action IN ('CLAIM','RELEASE','TRANSFER','TAKEOVER','AUTO_ASSIGN'));
