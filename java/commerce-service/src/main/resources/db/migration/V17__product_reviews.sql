-- Purchased-item reviews are independent of payment/refund ownership and never rewrite money.
CREATE TABLE product_review (
    review_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    line_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    product_name VARCHAR(120) NOT NULL,
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    variant VARCHAR(120) NOT NULL,
    rating INT NOT NULL,
    body VARCHAR(1000) NOT NULL,
    reply VARCHAR(1000) NULL,
    version BIGINT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_review_line(line_id),
    KEY idx_review_product(product_id,review_id),
    KEY idx_review_merchant(merchant_id,review_id),
    FOREIGN KEY(line_id) REFERENCES order_line(line_id),
    FOREIGN KEY(product_id) REFERENCES catalog_product(product_id),
    CHECK(rating BETWEEN 1 AND 5),
    CHECK(CHAR_LENGTH(TRIM(body)) BETWEEN 1 AND 1000),
    CHECK(reply IS NULL OR CHAR_LENGTH(TRIM(reply)) BETWEEN 1 AND 1000),
    CHECK(version BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE product_review_epoch (
    product_id VARCHAR(64) NOT NULL PRIMARY KEY,
    version BIGINT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES catalog_product(product_id),
    CHECK(version>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
