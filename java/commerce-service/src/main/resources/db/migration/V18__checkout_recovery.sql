-- Preserve public EXPIRED while recording an actual close; never close PAYMENT_PENDING.
ALTER TABLE checkout_draft
    ADD COLUMN close_reason VARCHAR(16) NULL,
    ADD CONSTRAINT chk_checkout_close_reason CHECK(close_reason IS NULL OR (status='CANCELLED' AND close_reason='EXPIRED')),
    ADD KEY idx_checkout_expiration(status,expires_at,draft_id);
ALTER TABLE checkout_payment_attempt
    ADD COLUMN next_reconcile_at DATETIME(6) NULL,
    ADD COLUMN reconcile_count INT NOT NULL DEFAULT 0,
    ADD COLUMN last_reconcile_error VARCHAR(32) NULL,
    ADD CONSTRAINT chk_checkout_reconcile_count CHECK(reconcile_count>=0);
UPDATE checkout_payment_attempt SET next_reconcile_at=created_at;
ALTER TABLE checkout_payment_attempt
    MODIFY COLUMN next_reconcile_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ADD KEY idx_checkout_reconcile(status,next_reconcile_at,attempt_id);
