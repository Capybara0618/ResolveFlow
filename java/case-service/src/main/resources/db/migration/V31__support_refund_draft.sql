-- One current draft per consultation. Confirmed case creation and this association share a transaction.
CREATE TABLE support_refund_draft (
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    draft_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    revision BIGINT NOT NULL,
    input_version BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(4000) NOT NULL,
    quantity INT NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL,
    expires_at TIMESTAMP(6) NOT NULL,
    case_id VARCHAR(64) NULL,
    CONSTRAINT fk_refund_draft_conversation FOREIGN KEY(conversation_id) REFERENCES support_conversation(conversation_id) ON DELETE CASCADE,
    CONSTRAINT ck_refund_draft_state CHECK(status IN ('DRAFT','CANCELLED','CONFIRMED')),
    CONSTRAINT ck_refund_draft_values CHECK(revision>0 AND input_version>0 AND quantity>0 AND amount_minor>0),
    CONSTRAINT ck_refund_draft_confirmed CHECK((status='CONFIRMED' AND case_id IS NOT NULL) OR (status<>'CONFIRMED' AND case_id IS NULL))
);
