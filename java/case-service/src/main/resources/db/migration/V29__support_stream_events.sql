-- Event cursors do not advance the input/message version used by the Agent fence.
ALTER TABLE support_conversation ADD COLUMN event_sequence BIGINT NOT NULL DEFAULT 0;
CREATE TABLE support_stream_event (
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_id BIGINT NOT NULL,
    run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    input_version BIGINT NOT NULL,
    fence BIGINT NOT NULL,
    attempt_id VARCHAR(64) NULL,
    kind VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY(conversation_id,event_id),
    CONSTRAINT fk_support_event_conversation FOREIGN KEY(conversation_id)
        REFERENCES support_conversation(conversation_id) ON DELETE CASCADE,
    CONSTRAINT ck_support_event_id CHECK(event_id>0 AND input_version>0 AND fence>=0)
);
