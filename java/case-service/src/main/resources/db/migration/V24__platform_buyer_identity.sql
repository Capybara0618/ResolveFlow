-- Legacy accounts and resource ownership remain untouched. New buyers are not merged by name/customer id.
CREATE TABLE platform_buyer (
    buyer_id VARCHAR(64) PRIMARY KEY,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_buyer_id CHECK (CHAR_LENGTH(buyer_id)>0)
);
ALTER TABLE identity_account DROP CHECK ck_identity_customer,
    MODIFY COLUMN merchant_id VARCHAR(64) NULL,
    ADD COLUMN buyer_id VARCHAR(64) NULL,
    ADD UNIQUE KEY uq_account_buyer (buyer_id),
    ADD CONSTRAINT fk_account_buyer FOREIGN KEY (buyer_id) REFERENCES platform_buyer(buyer_id),
    ADD CONSTRAINT ck_identity_binding CHECK (
      (buyer_id IS NOT NULL AND CHAR_LENGTH(buyer_id)>0 AND role='CUSTOMER' AND merchant_id IS NULL AND customer_id IS NULL)
      OR (buyer_id IS NULL AND merchant_id IS NOT NULL AND CHAR_LENGTH(merchant_id)>0
          AND ((role='CUSTOMER' AND customer_id IS NOT NULL AND CHAR_LENGTH(customer_id)>0)
               OR (role<>'CUSTOMER' AND customer_id IS NULL)))
    );
CREATE TABLE buyer_customer_binding (
    buyer_id VARCHAR(64) NOT NULL,
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (buyer_id,merchant_id),
    UNIQUE KEY uq_buyer_resource_owner (merchant_id,customer_id),
    CONSTRAINT fk_binding_buyer FOREIGN KEY (buyer_id) REFERENCES platform_buyer(buyer_id),
    CONSTRAINT fk_binding_merchant FOREIGN KEY (merchant_id) REFERENCES identity_merchant(merchant_id),
    CONSTRAINT ck_binding_customer CHECK (CHAR_LENGTH(customer_id)>0)
);
INSERT INTO platform_buyer (buyer_id) VALUES ('B-3001');
-- Explicit new demo identity, demo-buyer / demo-pass-4001. No legacy account is linked.
INSERT INTO identity_account (username,role,buyer_id,display_name,password_hash)
VALUES ('demo-buyer','CUSTOMER','B-3001','演示买家',
    'pbkdf2-sha256$120000$cmYtcGxhdGZvcm0tYnV5ZXItNDAwMQ==$vW9Ry9QgniqP6ekzR+fL6G7+ZNAcsrDRjyiVv4ziBi8=');
INSERT INTO buyer_customer_binding (buyer_id,merchant_id,customer_id) VALUES
('B-3001','M-1001','C-B3001-M1001'),('B-3001','M-1002','C-B3001-M1002');
