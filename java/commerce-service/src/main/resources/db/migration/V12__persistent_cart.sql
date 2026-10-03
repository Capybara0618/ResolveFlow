-- Independent cart state. Existing orders, drafts and payment/refund rows are untouched.
CREATE TABLE shopping_cart (
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(merchant_id,customer_id),
    CHECK(revision BETWEEN 0 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE shopping_cart_item (
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    observed_sku_version BIGINT NOT NULL,
    PRIMARY KEY(merchant_id,customer_id,sku_id),
    FOREIGN KEY(merchant_id,customer_id) REFERENCES shopping_cart(merchant_id,customer_id),
    FOREIGN KEY(sku_id) REFERENCES catalog_sku(sku_id),
    CHECK(quantity BETWEEN 1 AND 100),
    CHECK(observed_sku_version BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE shopping_cart_request (
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    result_revision BIGINT NOT NULL,
    PRIMARY KEY(merchant_id,customer_id,idempotency_key),
    FOREIGN KEY(merchant_id,customer_id) REFERENCES shopping_cart(merchant_id,customer_id),
    CHECK(result_revision BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
