-- Separate optimistic maintenance version from signed session invalidation.
ALTER TABLE identity_account ADD COLUMN account_version BIGINT NOT NULL DEFAULT 1,
    ADD CONSTRAINT ck_account_maintenance_version CHECK (account_version>=1),
    ADD KEY ix_identity_account_page (merchant_id,username);

CREATE TABLE identity_account_audit (
    audit_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    merchant_id VARCHAR(64) NOT NULL,
    target_username VARCHAR(120) NOT NULL,
    actor_username VARCHAR(120) NOT NULL,
    action VARCHAR(20) NOT NULL,
    account_version BIGINT NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    before_state JSON NULL,
    after_state JSON NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_account_audit_merchant FOREIGN KEY (merchant_id) REFERENCES identity_merchant(merchant_id),
    CONSTRAINT fk_account_audit_target FOREIGN KEY (target_username) REFERENCES identity_account(username),
    CONSTRAINT fk_account_audit_actor FOREIGN KEY (actor_username) REFERENCES identity_account(username),
    CONSTRAINT ck_account_audit_action CHECK (action IN ('CREATED','UPDATED','PASSWORD_RESET')),
    CONSTRAINT ck_account_audit_version CHECK (account_version>=1),
    KEY ix_account_audit_page (merchant_id,target_username,audit_id DESC)
);
