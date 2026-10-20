-- Independent consultation records. No foreign keys/writes into refund Case or money tables.
CREATE TABLE support_conversation (
    sort_id BIGINT NOT NULL AUTO_INCREMENT UNIQUE,
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    buyer_id VARCHAR(64) NOT NULL,
    merchant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    line_id VARCHAR(64) NOT NULL,
    store_name VARCHAR(120) NOT NULL,
    product_json JSON NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    UNIQUE KEY uq_support_buyer_line(buyer_id,line_id),
    INDEX ix_support_buyer_page(buyer_id,sort_id),
    CONSTRAINT fk_support_binding FOREIGN KEY(buyer_id,merchant_id) REFERENCES buyer_customer_binding(buyer_id,merchant_id),
    CONSTRAINT ck_support_version CHECK(version>0)
);
CREATE TABLE support_ticket (
    sort_id BIGINT NOT NULL AUTO_INCREMENT UNIQUE,
    ticket_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    merchant_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    summary VARCHAR(2000) NOT NULL,
    shared_json JSON NOT NULL,
    INDEX ix_support_ticket_page(merchant_id,sort_id),
    CONSTRAINT fk_ticket_conversation FOREIGN KEY(conversation_id) REFERENCES support_conversation(conversation_id),
    CONSTRAINT ck_support_ticket_status CHECK(status IN ('PENDING','WAITING_CUSTOMER','REPLIED','RESOLVED'))
);
CREATE TABLE support_message (
    message_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sequence BIGINT NOT NULL,
    author VARCHAR(16) NOT NULL,
    recipient VARCHAR(16) NOT NULL,
    actor VARCHAR(120) NOT NULL,
    text VARCHAR(4000) NOT NULL,
    ticket_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_support_message_sequence(conversation_id,sequence),
    INDEX ix_ticket_messages(ticket_id,sequence),
    CONSTRAINT fk_message_conversation FOREIGN KEY(conversation_id) REFERENCES support_conversation(conversation_id),
    CONSTRAINT fk_message_ticket FOREIGN KEY(ticket_id) REFERENCES support_ticket(ticket_id),
    CONSTRAINT ck_support_author CHECK(author IN ('CUSTOMER','MERCHANT')),
    CONSTRAINT ck_support_recipient CHECK(recipient IN ('ASSISTANT','MERCHANT','CUSTOMER')),
    CONSTRAINT ck_support_message_route CHECK(
        (author='CUSTOMER' AND recipient='ASSISTANT' AND ticket_id IS NULL)
        OR (author='CUSTOMER' AND recipient='MERCHANT' AND ticket_id IS NOT NULL)
        OR (author='MERCHANT' AND recipient='CUSTOMER' AND ticket_id IS NOT NULL))
);
CREATE TABLE support_receipt (
    conversation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    actor VARCHAR(120) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    request_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_json JSON NOT NULL,
    response_json JSON NOT NULL,
    PRIMARY KEY(conversation_id,actor,operation,request_key),
    CONSTRAINT fk_receipt_conversation FOREIGN KEY(conversation_id) REFERENCES support_conversation(conversation_id)
);
