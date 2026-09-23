-- C05.2b: the commerce-service result outbox.
--
-- The mirror of the case side's event_outbox (case-service V12), and the same rule (docs/domain-model.md:45,
-- docs/core-contracts.md:67): the event is written in the transaction that produced the fact it reports.
-- RefundSettlementService says plainly that it does not write the result event because that was C05's business;
-- this table and its writer are that business. A settlement that committed without its event would leave the
-- case waiting forever for an outcome that this service already decided, and there is no later moment at which
-- anyone could reconstruct that the event was owed.
--
-- Why the finished envelope is stored rather than the pieces to build one: the signature is over the exact
-- bytes that will be published, so it has to be computed at write time and stored with them. Re-signing at send
-- time would sign whatever the code looks like then rather than what the transaction decided, and the consumer
-- verifies exactly what the producer signed.
--
-- No foreign key to refund_operation, unlike the case side's case_execution_command:
--   * the row's identity is its own event_id, and the operation is named inside the *signed* payload. An FK
--     would be a second place to state the same relationship, free to disagree with the signature;
--   * the delivery loop must be able to read and send a row without joining the money tables, which is also
--     what keeps the loop's query off the refund locks.
--
-- Migrations are append-only (docs/engineering.md:64).

CREATE TABLE event_outbox (
    -- The event's own identity, allocated before delivery is attempted. A redelivery is the transport's
    -- business (at-least-once); this id is what lets the case side's inbox drop a repeat.
    event_id        CHAR(36)     NOT NULL,
    event_type      VARCHAR(32)  NOT NULL,
    schema_version  INT          NOT NULL,
    merchant_id     VARCHAR(64)  NOT NULL,
    topic           VARCHAR(64)  NOT NULL,
    producer        VARCHAR(32)  NOT NULL,
    -- The signed envelope, exactly as it will be published. Text rather than a JSON column on purpose: a JSON
    -- column is free to reformat what it is given, and a reformatted document is no longer the byte sequence
    -- that was signed.
    envelope        LONGTEXT     NOT NULL,
    signature       VARCHAR(128) NOT NULL,
    signing_key_id  VARCHAR(64)  NOT NULL,
    -- PENDING  : committed, not yet handed to the transport.
    -- PUBLISHED: the transport accepted it. At-least-once means this is not the same as "the case applied it".
    -- DEAD     : attempts exhausted. Kept, never deleted: a dropped result is a fact an operator needs, and the
    --            row is what a manual replay would start from.
    status          VARCHAR(16)  NOT NULL,
    attempts        INT          NOT NULL DEFAULT 0,
    last_error      VARCHAR(500) NULL,
    next_attempt_at DATETIME(6)  NULL,
    created_at      DATETIME(6)  NOT NULL,
    published_at    DATETIME(6)  NULL,
    PRIMARY KEY (event_id),
    -- The delivery loop asks for "due, oldest first"; this is that query's index.
    KEY idx_event_outbox_due (status, next_attempt_at, created_at),
    KEY idx_event_outbox_merchant (merchant_id, created_at),
    CONSTRAINT chk_event_outbox_status CHECK (status IN ('PENDING', 'PUBLISHED', 'DEAD')),
    CONSTRAINT chk_event_outbox_attempts CHECK (attempts >= 0),
    CONSTRAINT chk_event_outbox_schema_version CHECK (schema_version = 2),
    -- A published row has a time and no further attempt scheduled; an unpublished row has neither. One fact,
    -- one answer, the same rule the money tables use.
    CONSTRAINT chk_event_outbox_published
        CHECK ((status = 'PUBLISHED') = (published_at IS NOT NULL))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;