-- Append-only simulated checkout. Existing paid orders/refunds are untouched.
-- V10 used an unnamed status CHECK; locate its generated name rather than assume a counter.
SET @checkout_status_check = (
    SELECT cc.CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS cc
    JOIN information_schema.TABLE_CONSTRAINTS tc
      ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_SCHEMA=DATABASE() AND tc.TABLE_NAME='checkout_draft'
      AND cc.CHECK_CLAUSE LIKE '%status%'
);
SET @checkout_alter = CONCAT('ALTER TABLE checkout_draft DROP CHECK `', @checkout_status_check, '`');
PREPARE checkout_stmt FROM @checkout_alter;
EXECUTE checkout_stmt;
DEALLOCATE PREPARE checkout_stmt;
ALTER TABLE checkout_draft
    ADD COLUMN category VARCHAR(64) NULL,
    ADD COLUMN order_id CHAR(36) NULL,
    ADD COLUMN line_id VARCHAR(64) NULL,
    ADD COLUMN paid_at DATETIME(6) NULL,
    ADD CONSTRAINT chk_checkout_state CHECK(status IN ('WAITING_PAYMENT','PAYMENT_PENDING','PAID','CANCELLED')),
    ADD CONSTRAINT chk_checkout_publication CHECK(
        (status='PAID' AND order_id IS NOT NULL AND line_id IS NOT NULL AND paid_at IS NOT NULL)
        OR (status<>'PAID' AND order_id IS NULL AND line_id IS NULL AND paid_at IS NULL)),
    ADD UNIQUE KEY uq_checkout_order(order_id),
    ADD UNIQUE KEY uq_checkout_line(line_id),
    ADD FOREIGN KEY(order_id) REFERENCES orders(order_id),
    ADD FOREIGN KEY(line_id) REFERENCES order_line(line_id);
-- Only the new category snapshot is populated for pre-migration drafts.
UPDATE checkout_draft d JOIN catalog_product p ON p.product_id=d.product_id SET d.category=p.category;
ALTER TABLE checkout_draft MODIFY COLUMN category VARCHAR(64) NOT NULL;
CREATE TABLE checkout_payment_attempt (
    attempt_id CHAR(36) NOT NULL PRIMARY KEY,
    draft_id CHAR(36) NOT NULL,
    sequence_no INT NOT NULL,
    idempotency_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    total_amount BIGINT NOT NULL,
    currency CHAR(3) NOT NULL,
    status VARCHAR(16) NOT NULL,
    order_id CHAR(36) NOT NULL,
    line_id VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    paid_at DATETIME(6) NULL,
    UNIQUE KEY uq_checkout_attempt_key(draft_id,idempotency_key),
    UNIQUE KEY uq_checkout_attempt_sequence(draft_id,sequence_no),
    UNIQUE KEY uq_checkout_attempt_order(order_id),
    UNIQUE KEY uq_checkout_attempt_line(line_id),
    FOREIGN KEY(draft_id) REFERENCES checkout_draft(draft_id),
    CHECK(sequence_no>0 AND total_amount>0 AND total_amount<=10000000000 AND currency='CNY'),
    CHECK(status IN ('UNKNOWN','SUCCEEDED','FAILED')),
    CHECK((status='UNKNOWN')=(finished_at IS NULL)),
    CHECK((status='SUCCEEDED')=(paid_at IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE simulated_checkout_receipt (
    attempt_id CHAR(36) NOT NULL PRIMARY KEY,
    total_amount BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    finished_at DATETIME(6) NOT NULL,
    CHECK(total_amount>0 AND total_amount<=10000000000),
    CHECK(status IN ('SUCCEEDED','FAILED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
