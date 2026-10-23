-- Provisional view only. Never copied to support_message or refund/share inputs.
ALTER TABLE support_agent_turn
    ADD COLUMN progress_sequence BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN progress_event_count INT NOT NULL DEFAULT 0,
    ADD COLUMN progress_batch_json JSON NULL,
    ADD COLUMN progress_json JSON NULL;
