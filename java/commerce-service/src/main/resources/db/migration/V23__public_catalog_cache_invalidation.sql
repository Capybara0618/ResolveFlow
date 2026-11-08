-- A pending invalidation commits with the catalog/review write and survives Redis outages or restarts.
CREATE TABLE public_catalog_cache_invalidation (
    cache_namespace VARCHAR(120) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    targets TINYINT NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY(cache_namespace,product_id),
    KEY idx_public_cache_invalidation(updated_at),
    CHECK(targets BETWEEN 1 AND 3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
