-- Immutable historical owner map used only by this data migration.
CREATE TABLE IF NOT EXISTS buyer_identity_legacy (
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    buyer_id VARCHAR(64) NOT NULL,
    PRIMARY KEY(merchant_id,customer_id),
    UNIQUE KEY uq_migration_buyer_store(buyer_id,merchant_id)
);
-- Fresh installations contain exactly these immutable historical seed owners.
-- Existing installations preload the complete map with buyer_identity_migration.py.
INSERT IGNORE INTO buyer_identity_legacy VALUES ('M-1001','C-2002','B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80');
INSERT IGNORE INTO buyer_identity_legacy VALUES ('M-1001','C-2003','B-legacy-085a244f8f8acaf20c76a2191b6ebde0ea6d70df');
INSERT IGNORE INTO buyer_identity_legacy VALUES ('M-1002','C-2004','B-legacy-6f808772ade9cc75fd3896626db511b718eebaa2');
INSERT IGNORE INTO buyer_identity_legacy VALUES ('M-1002','C-2005','B-legacy-cbfbc19e76c82c1141e25df5fdf9c38093add896');
INSERT IGNORE INTO buyer_identity_legacy VALUES ('M-1001','C-B3001-M1001','B-3001'),('M-1002','C-B3001-M1002','B-3001');
-- Validate every table before changing any identity value or column.
DELIMITER $$
CREATE PROCEDURE assert_buyer_ownership()
BEGIN
    IF EXISTS(SELECT 1 FROM orders t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in orders; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM order_line t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in order_line; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM checkout_draft t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in checkout_draft; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM shopping_cart t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in shopping_cart; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM shopping_cart_item t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in shopping_cart_item; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM shopping_cart_request t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in shopping_cart_request; run identity preflight';
    END IF;
    IF EXISTS(SELECT 1 FROM product_review t LEFT JOIN buyer_identity_legacy m
        ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unmapped buyer in product_review; run identity preflight';
    END IF;
END$$
DELIMITER ;
CALL assert_buyer_ownership();
DROP PROCEDURE assert_buyer_ownership;
SET @buyer_migration_foreign_keys=@@FOREIGN_KEY_CHECKS;
SET FOREIGN_KEY_CHECKS=0;
UPDATE orders t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE orders RENAME COLUMN customer_id TO buyer_id;
UPDATE order_line t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE order_line RENAME COLUMN customer_id TO buyer_id;
UPDATE checkout_draft t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE checkout_draft RENAME COLUMN customer_id TO buyer_id;
UPDATE shopping_cart t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE shopping_cart RENAME COLUMN customer_id TO buyer_id;
UPDATE shopping_cart_item t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE shopping_cart_item RENAME COLUMN customer_id TO buyer_id;
UPDATE shopping_cart_request t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE shopping_cart_request RENAME COLUMN customer_id TO buyer_id;
UPDATE product_review t JOIN buyer_identity_legacy m
ON t.merchant_id=m.merchant_id AND t.customer_id=m.customer_id SET t.customer_id=m.buyer_id;
ALTER TABLE product_review RENAME COLUMN customer_id TO buyer_id;
SET FOREIGN_KEY_CHECKS=@buyer_migration_foreign_keys;
