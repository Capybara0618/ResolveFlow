CREATE TABLE account_recovery (
    username VARCHAR(120) NOT NULL PRIMARY KEY,
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    issued_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_recovery_account FOREIGN KEY(username) REFERENCES identity_account(username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
