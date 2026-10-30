ALTER TABLE identity_account
    ADD COLUMN phone VARCHAR(32) NULL,
    ADD COLUMN gender VARCHAR(20) NULL,
    ADD COLUMN birth_date DATE NULL,
    ADD COLUMN login_name VARCHAR(120) NULL,
    ADD COLUMN login_key VARCHAR(120) GENERATED ALWAYS AS (COALESCE(login_name, username)) STORED,
    ADD UNIQUE KEY uk_account_login_key (login_key);
