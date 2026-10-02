-- Append-only compatibility for explicit administrator ownership and 120-character persisted subjects.
ALTER TABLE case_evidence
    DROP CHECK chk_evidence_appended_role,
    MODIFY COLUMN appended_by VARCHAR(120) NOT NULL,
    ADD CONSTRAINT chk_evidence_appended_role CHECK (appended_role IN ('CUSTOMER','REVIEWER','MERCHANT_ADMIN','OPERATOR'));
ALTER TABLE case_authorization
    DROP CHECK chk_authorization_decided_role,
    MODIFY COLUMN decided_by VARCHAR(120) NULL,
    ADD CONSTRAINT chk_authorization_decided_role CHECK
        (decided_role IS NULL OR decided_role IN ('CUSTOMER','REVIEWER','MERCHANT_ADMIN','OPERATOR'));
ALTER TABLE case_proposal
    DROP CHECK chk_case_proposal_authored_role,
    MODIFY COLUMN authored_by VARCHAR(120) NULL,
    ADD CONSTRAINT chk_case_proposal_authored_role CHECK
        (authored_role IS NULL OR authored_role IN ('CUSTOMER','REVIEWER','MERCHANT_ADMIN','OPERATOR'));
