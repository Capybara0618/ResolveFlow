-- Immutable historical owner map used only by this data migration.
CREATE TABLE IF NOT EXISTS buyer_identity_legacy (
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    buyer_id VARCHAR(64) NOT NULL,
    PRIMARY KEY(merchant_id,customer_id),
    UNIQUE KEY uq_migration_buyer_store(buyer_id,merchant_id)
);
INSERT INTO buyer_identity_legacy(merchant_id,customer_id,buyer_id)
SELECT merchant_id,customer_id,buyer_id FROM buyer_customer_binding
ON DUPLICATE KEY UPDATE buyer_id=buyer_identity_legacy.buyer_id;
INSERT INTO buyer_identity_legacy(merchant_id,customer_id,buyer_id)
SELECT merchant_id,customer_id,CONCAT('B-legacy-',SUBSTRING(SHA2(CONCAT('[',JSON_QUOTE(merchant_id),',',JSON_QUOTE(customer_id),']'),256),1,40)) FROM identity_account
WHERE role='CUSTOMER' AND buyer_id IS NULL
ON DUPLICATE KEY UPDATE buyer_id=buyer_identity_legacy.buyer_id;
DELIMITER $$
CREATE PROCEDURE assert_case_buyer_ownership()
BEGIN
    IF EXISTS(SELECT 1 FROM aftersale_case c LEFT JOIN buyer_identity_legacy m
        ON c.merchant_id=m.merchant_id AND c.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped case buyer; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM support_conversation c LEFT JOIN buyer_identity_legacy m
        ON c.merchant_id=m.merchant_id AND c.customer_id=m.customer_id
        WHERE m.buyer_id IS NULL OR c.buyer_id<>m.buyer_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Conflicting consultation buyer';
    END IF;
END$$
DELIMITER ;
CALL assert_case_buyer_ownership();
DROP PROCEDURE assert_case_buyer_ownership;
INSERT IGNORE INTO platform_buyer(buyer_id) SELECT buyer_id FROM buyer_identity_legacy;
ALTER TABLE identity_account DROP CHECK ck_identity_binding;
UPDATE identity_account a JOIN buyer_identity_legacy m ON a.merchant_id=m.merchant_id AND a.customer_id=m.customer_id
SET a.buyer_id=m.buyer_id,a.merchant_id=NULL,a.identity_version=a.identity_version+1
WHERE a.role='CUSTOMER' AND a.buyer_id IS NULL;
ALTER TABLE identity_account DROP COLUMN customer_id,
    ADD CONSTRAINT ck_identity_binding CHECK (
        (role='CUSTOMER' AND buyer_id IS NOT NULL AND merchant_id IS NULL)
        OR (role='PLATFORM_ADMIN' AND buyer_id IS NULL AND merchant_id IS NULL)
        OR (role NOT IN ('CUSTOMER','PLATFORM_ADMIN') AND buyer_id IS NULL AND merchant_id IS NOT NULL));
UPDATE aftersale_case c JOIN buyer_identity_legacy m
ON c.merchant_id=m.merchant_id AND c.customer_id=m.customer_id SET c.customer_id=m.buyer_id;
ALTER TABLE aftersale_case RENAME COLUMN customer_id TO buyer_id;
ALTER TABLE support_conversation DROP FOREIGN KEY fk_support_binding, DROP COLUMN customer_id;
DROP TABLE buyer_customer_binding;
