-- C03.3a: the authorisation a human decides on, and the payload it fixes.
--
-- 1. This row is created in the same transaction as the validated proposal it comes from (and the inbox
--    row, the status transition and the trajectory row). docs/core-contracts.md:67 puts the inbox, the
--    business result and the local event in one transaction; an authorisation is a business result, so
--    "the proposal was checked" and "there is something to approve" cannot be true separately.
--
-- 2. planned_operation_id is allocated here, before anyone decides (docs/core-contracts.md:19). That is
--    what makes a retry unable to pay twice: the id is part of the hashed payload, so a second attempt
--    either reuses this operation or is a different, additionally authorised payment. The unique key
--    makes it a property of the schema rather than a habit of the code.
--
-- 3. payload_hash is stored rather than recomputed on read for the same reason the proposal stores it:
--    the value a human approves has to be the value that was fixed at creation, and a hash recomputed
--    from columns that have since changed would silently approve something else. The twelve covered
--    fields are reconstructible from this row and the case row, so the hash can still be re-derived and
--    compared at consumption time (C04) instead of trusted.
--
-- 4. amount_minor/quantity/currency/policy_version are the rest of the hashed payload. They are stored
--    even though the proposal carries a recomputed amount, because the authorisation is the fixed
--    version of that amount: a later proposal, a later policy import or a later line change must not be
--    able to move what this row already promised.
--
-- 5. status starts at PENDING_REVIEW and the decision columns arrive with the decision route (C03.3b):
--    a column nothing writes is a column a reader has to guess about.

CREATE TABLE case_authorization (
    authorization_id        CHAR(36)     NOT NULL,
    case_id                 CHAR(36)     NOT NULL,
    authorization_version   BIGINT       NOT NULL,
    status                  VARCHAR(16)  NOT NULL,
    action                  VARCHAR(16)  NOT NULL,
    input_revision          BIGINT       NOT NULL,
    proposal_id             CHAR(36)     NOT NULL,
    planned_operation_id    CHAR(36)     NOT NULL,
    payload_hash            CHAR(64)     NOT NULL,
    amount_minor            BIGINT       NOT NULL,
    quantity                INT          NOT NULL,
    currency                CHAR(3)      NOT NULL,
    policy_version          VARCHAR(64)  NOT NULL,
    expires_at              DATETIME(6)  NULL,
    created_at              DATETIME(6)  NOT NULL,
    updated_at              DATETIME(6)  NOT NULL,
    PRIMARY KEY (authorization_id),
    UNIQUE KEY uq_authorization_operation (planned_operation_id),
    KEY idx_authorization_case (case_id, created_at),
    CONSTRAINT fk_authorization_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT fk_authorization_proposal FOREIGN KEY (proposal_id) REFERENCES case_proposal (proposal_id),
    CONSTRAINT chk_authorization_status CHECK (
        status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'EXPIRED', 'REVOKED', 'CONSUMED')
    ),
    -- REFUND is the only executable action in core (docs/core-scope.md:9), so a row for anything else
    -- would be an authorisation this service could never execute.
    CONSTRAINT chk_authorization_action CHECK (action = 'REFUND'),
    CONSTRAINT chk_authorization_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_authorization_version CHECK (authorization_version >= 1),
    CONSTRAINT chk_authorization_amount CHECK (amount_minor >= 1 AND amount_minor <= 1000000000),
    CONSTRAINT chk_authorization_quantity CHECK (quantity >= 1),
    CONSTRAINT chk_authorization_currency CHECK (currency = 'CNY'),
    CONSTRAINT chk_authorization_hash CHECK (REGEXP_LIKE(payload_hash, '^[a-f0-9]{64}$'))
) ENGINE = InnoDB;