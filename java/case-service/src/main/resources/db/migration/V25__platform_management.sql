ALTER TABLE identity_account DROP CHECK ck_identity_role, DROP CHECK ck_identity_binding,
    ADD CONSTRAINT ck_identity_role CHECK (role IN ('CUSTOMER','REVIEWER','MERCHANT_ADMIN','OPERATOR','PLATFORM_ADMIN')),
    ADD CONSTRAINT ck_identity_binding CHECK (
      (role='PLATFORM_ADMIN' AND merchant_id IS NULL AND customer_id IS NULL AND buyer_id IS NULL)
      OR (buyer_id IS NOT NULL AND role='CUSTOMER' AND merchant_id IS NULL AND customer_id IS NULL)
      OR (buyer_id IS NULL AND merchant_id IS NOT NULL
          AND ((role='CUSTOMER' AND customer_id IS NOT NULL) OR (role NOT IN ('CUSTOMER','PLATFORM_ADMIN') AND customer_id IS NULL)))
    );
ALTER TABLE identity_merchant
    ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT '',
    ADD COLUMN version BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN desired_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN sync_state VARCHAR(16) NOT NULL DEFAULT 'READY';
CREATE TABLE platform_management_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    actor VARCHAR(120) NOT NULL,
    target VARCHAR(120) NOT NULL,
    action VARCHAR(40) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
