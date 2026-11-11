CREATE TABLE catalog_search_outbox (
    event_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id VARCHAR(64) NOT NULL,
    product_version BIGINT NOT NULL,
    payload JSON NOT NULL,
    UNIQUE KEY uq_catalog_search_revision (product_id, product_version)
);
