-- Existing flattened single-SKU drafts remain valid. Only new MULTI drafts use child snapshots.
SET @checkout_amount_check = (
    SELECT cc.CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS cc
    JOIN information_schema.TABLE_CONSTRAINTS tc
      ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_SCHEMA=DATABASE() AND tc.TABLE_NAME='checkout_draft'
      AND cc.CHECK_CLAUSE LIKE '%unit_amount%'
);
SET @checkout_amount_alter = CONCAT('ALTER TABLE checkout_draft DROP CHECK `', @checkout_amount_check, '`');
PREPARE checkout_amount_stmt FROM @checkout_amount_alter;
EXECUTE checkout_amount_stmt;
DEALLOCATE PREPARE checkout_amount_stmt;
ALTER TABLE checkout_draft
    ADD COLUMN kind VARCHAR(8) NOT NULL DEFAULT 'SINGLE',
    ADD COLUMN line_count INT NOT NULL DEFAULT 1,
    ADD COLUMN cart_revision BIGINT NULL,
    ADD COLUMN multiline_request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD CONSTRAINT chk_checkout_amount CHECK(unit_amount>0 AND total_amount>0 AND
      ((kind='SINGLE' AND total_amount=unit_amount*quantity AND total_amount<=10000000000 AND line_count=1 AND cart_revision IS NULL AND multiline_request_hash IS NULL)
       OR (kind='MULTI' AND total_amount<=1000000000 AND line_count BETWEEN 1 AND 20 AND cart_revision IS NOT NULL AND cart_revision BETWEEN 0 AND 9007199254740990 AND multiline_request_hash IS NOT NULL)));
CREATE TABLE checkout_draft_line (
    draft_id CHAR(36) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    product_name VARCHAR(120) NOT NULL,
    variant VARCHAR(120) NOT NULL,
    asset_key VARCHAR(32) NOT NULL,
    category VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    unit_amount BIGINT NOT NULL,
    line_amount BIGINT NOT NULL,
    sku_version BIGINT NOT NULL,
    PRIMARY KEY(draft_id,sku_id),
    FOREIGN KEY(draft_id) REFERENCES checkout_draft(draft_id),
    CHECK(quantity BETWEEN 1 AND 100 AND unit_amount>0 AND line_amount=unit_amount*quantity AND line_amount<=1000000000),
    CHECK(sku_version BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE checkout_payment_line (
    attempt_id CHAR(36) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    line_id VARCHAR(64) NOT NULL,
    PRIMARY KEY(attempt_id,sku_id),
    UNIQUE KEY uq_attempt_snapshot_line(line_id),
    FOREIGN KEY(attempt_id) REFERENCES checkout_payment_attempt(attempt_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
