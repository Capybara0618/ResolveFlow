CREATE TABLE checkout_shipping (
    draft_id CHAR(36) PRIMARY KEY,
    snapshot_json JSON NOT NULL,
    CONSTRAINT fk_checkout_shipping_draft FOREIGN KEY(draft_id) REFERENCES checkout_draft(draft_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
