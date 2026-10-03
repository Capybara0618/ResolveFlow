-- Append-only synthetic catalog. No changes to paid orders, policies, identities or ledgers.
CREATE TABLE catalog_store (
    store_id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(500) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE catalog_product (
    product_id VARCHAR(64) NOT NULL PRIMARY KEY,
    store_id VARCHAR(64) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(1000) NOT NULL,
    category VARCHAR(64) NOT NULL,
    asset_key VARCHAR(32) NOT NULL,
    listed BOOLEAN NOT NULL DEFAULT TRUE,
    KEY idx_catalog_store(store_id,product_id),
    FOREIGN KEY(store_id) REFERENCES catalog_store(store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE catalog_sku (
    sku_id VARCHAR(64) NOT NULL PRIMARY KEY,
    product_id VARCHAR(64) NOT NULL,
    variant VARCHAR(120) NOT NULL,
    unit_amount BIGINT NOT NULL,
    max_quantity INT NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    listed BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY(product_id) REFERENCES catalog_product(product_id),
    CHECK(unit_amount>0 AND unit_amount<=100000000),
    CHECK(max_quantity BETWEEN 1 AND 100),
    CHECK(version BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE checkout_draft (
    draft_id CHAR(36) NOT NULL PRIMARY KEY,
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    product_name VARCHAR(120) NOT NULL,
    store_name VARCHAR(120) NOT NULL,
    asset_key VARCHAR(32) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    variant VARCHAR(120) NOT NULL,
    quantity INT NOT NULL,
    unit_amount BIGINT NOT NULL,
    total_amount BIGINT NOT NULL,
    sku_version BIGINT NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    status VARCHAR(32) NOT NULL DEFAULT 'WAITING_PAYMENT',
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_draft_request(merchant_id,customer_id,idempotency_key),
    KEY idx_draft_scope(merchant_id,customer_id,created_at,draft_id),
    CHECK(quantity BETWEEN 1 AND 100),
    CHECK(unit_amount>0 AND total_amount=unit_amount*quantity AND total_amount<=10000000000),
    CHECK(currency='CNY'),
    CHECK(sku_version BETWEEN 1 AND 9007199254740991),
    CHECK(status='WAITING_PAYMENT'),
    CHECK(expires_at>created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO catalog_store(store_id,name,description) VALUES
('M-1001','松间数码','日常工作与聆听的数码用品'),('M-1002','拾光家居','给生活添一份舒适');
INSERT INTO catalog_product(product_id,store_id,name,description,category,asset_key) VALUES
('P-1001','M-1001','无线降噪耳机','包耳式设计，适合通勤与专注工作。','electronics','headphones'),
('P-1002','M-1001','机械键盘','清晰触感，简洁配色，为桌面工作而设计。','electronics','keyboard'),
('P-1003','M-1001','无线鼠标','轻巧机身，日常办公的灵活选择。','electronics','mouse'),
('P-2001','M-1002','桌面台灯','柔和光线与简洁轮廓，照亮阅读时光。','home','lamp'),
('P-2002','M-1002','保温杯','简约杯身，随身携带的日常饮水用品。','home','cup'),
('P-2003','M-1002','棉麻靠枕','柔软触感，适合沙发与阅读角。','home','pillow');
INSERT INTO catalog_sku(sku_id,product_id,variant,unit_amount,max_quantity) VALUES
('SKU-1001-BLACK','P-1001','黑色',32900,10),('SKU-1001-SILVER','P-1001','银色',34900,10),
('SKU-1002-WHITE','P-1002','白色',19900,10),('SKU-1003-GRAY','P-1003','灰色',8900,10),
('SKU-2001-CREAM','P-2001','米白色',12900,10),('SKU-2002-SILVER','P-2002','银色',8900,10),
('SKU-2003-BEIGE','P-2003','米色',5900,10);
