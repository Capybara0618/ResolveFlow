ALTER TABLE support_message DROP CHECK ck_support_author, DROP CHECK ck_support_message_route,
    ADD COLUMN assistant_json JSON NULL,
    ADD CONSTRAINT ck_support_author CHECK(author IN ('CUSTOMER','MERCHANT','ASSISTANT')),
    ADD CONSTRAINT ck_support_message_route CHECK(
        (author='CUSTOMER' AND recipient='ASSISTANT' AND ticket_id IS NULL)
        OR (author='CUSTOMER' AND recipient='MERCHANT' AND ticket_id IS NOT NULL)
        OR (author='MERCHANT' AND recipient='CUSTOMER' AND ticket_id IS NOT NULL)
        OR (author='ASSISTANT' AND recipient='CUSTOMER' AND ticket_id IS NULL AND assistant_json IS NOT NULL));
ALTER TABLE support_ticket ADD COLUMN report_json JSON NULL;
CREATE TABLE support_agent_turn (
    run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    input_version BIGINT NOT NULL,
    actor VARCHAR(120) NOT NULL,
    identity_version BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    reason VARCHAR(128) NULL,
    fence BIGINT NOT NULL DEFAULT 0,
    lease_until TIMESTAMP(6) NULL,
    deadline_at TIMESTAMP(6) NULL,
    not_before TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    context_json JSON NULL,
    result_json JSON NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_support_turn_input(conversation_id,input_version),
    INDEX ix_support_turn_due(status,not_before,lease_until),
    CONSTRAINT fk_support_turn_conversation FOREIGN KEY(conversation_id) REFERENCES support_conversation(conversation_id),
    CONSTRAINT ck_support_turn_status CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','STALE'))
);
