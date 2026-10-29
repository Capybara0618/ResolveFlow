ALTER TABLE identity_account
    ADD COLUMN avatar_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD COLUMN profile_version BIGINT NOT NULL DEFAULT 1;

CREATE TABLE buyer_address (
    address_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    buyer_id VARCHAR(64) NOT NULL,
    recipient VARCHAR(80) NOT NULL,
    phone VARCHAR(32) NOT NULL,
    province VARCHAR(80) NOT NULL,
    city VARCHAR(80) NOT NULL,
    district VARCHAR(80) NOT NULL,
    detail VARCHAR(300) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 1,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX ix_buyer_address_owner(buyer_id,deleted,is_default),
    CONSTRAINT ck_address_version CHECK(version>0)
);
