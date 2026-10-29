CREATE TABLE catalog_media (
    media_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    merchant_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX ix_catalog_media_owner(merchant_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
