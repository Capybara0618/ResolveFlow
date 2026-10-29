CREATE TABLE catalog_product_presentation (
    product_id VARCHAR(64) PRIMARY KEY,
    version BIGINT NOT NULL,
    images JSON NOT NULL,
    specifications JSON NOT NULL,
    shipping_note VARCHAR(500) NOT NULL,
    aftercare_note VARCHAR(1000) NOT NULL,
    CONSTRAINT fk_presentation_product FOREIGN KEY(product_id) REFERENCES catalog_product(product_id),
    CONSTRAINT ck_product_presentation_version CHECK(version>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE catalog_store_presentation (
    store_id VARCHAR(64) PRIMARY KEY,
    version BIGINT NOT NULL,
    introduction VARCHAR(500) NOT NULL,
    logo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    contact_phone VARCHAR(32) NOT NULL,
    service_hours VARCHAR(80) NOT NULL,
    CONSTRAINT fk_presentation_store FOREIGN KEY(store_id) REFERENCES catalog_store(store_id),
    CONSTRAINT ck_store_presentation_version CHECK(version>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
