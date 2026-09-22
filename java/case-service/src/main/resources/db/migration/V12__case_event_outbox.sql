-- C05.1a: the case-service event outbox.
--
-- The envelope that leaves this service is written here **in the same transaction as the effect that
-- produced it** (docs/domain-model.md:45, docs/core-contracts.md:67: inbox、业务结果和本地事件在同一事务).
-- That co-transaction is the whole design: an event that committed while its cause rolled back would
-- announce something that did not happen, and an effect that committed without its event would be invisible
-- to the other service. Neither half can be retried into existence afterwards.
--
-- Why the row stores the **finished envelope** rather than the pieces to build one:
--   * the signature is over the exact bytes that will be sent, so it has to be computed at write time and
--     stored with them. Re-deriving it later would sign whatever the code looks like then, not what the
--     transaction decided;
--   * the consumer verifies exactly what the producer signed, so storing the signed document removes any
--     chance of the two disagreeing about canonicalisation.
--
-- Migrations are append-only (docs/engineering.md:64).

CREATE TABLE event_outbox (
    -- The event's own identity, allocated by the writer so it exists before delivery is attempted. A
    -- redelivery is the transport's business (at-least-once, docs/core-contracts.md:67); this id is what
    -- lets the consumer's inbox drop a repeat.
    event_id        CHAR(36)     NOT NULL,
    event_type      VARCHAR(32)  NOT NULL,
    schema_version  INT          NOT NULL,
    merchant_id     VARCHAR(64)  NOT NULL,
    topic           VARCHAR(64)  NOT NULL,
    producer        VARCHAR(32)  NOT NULL,
    -- The signed envelope, exactly as it will be published. Stored as text rather than as a JSON column on
    -- purpose: a JSON column is free to reformat what it is given, and a reformatted document is no longer
    -- the byte sequence that was signed. The consumer verifies what the producer signed, so the stored form
    -- has to be that form.
    envelope        LONGTEXT     NOT NULL,
    -- The signature is inside `envelope` too; this column exists so an operator can see at a glance that a
    -- row is signed without parsing JSON, and so a later migration can index on it if a trust list changes.
    signature       VARCHAR(128) NOT NULL,
    signing_key_id  VARCHAR(64)  NOT NULL,
    -- PENDING  : committed, not yet handed to the transport.
    -- PUBLISHED: the transport accepted it. At-least-once means this is not the same as "the consumer
    --            applied it" — the consumer's inbox is what makes a duplicate harmless.
    -- DEAD     : attempts exhausted. Kept, never deleted: a dropped event is a fact the operator needs, and
    --            the row is what a manual replay would start from.
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
    -- A published row has a time and no further attempt scheduled; an unpublished row has neither. This is
    -- the same "one fact, one answer" rule the money tables use.
    CONSTRAINT chk_event_outbox_published
        CHECK ((status = 'PUBLISHED') = (published_at IS NOT NULL))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- One core command per authorisation, enforced here rather than by a reader remembering to check: the
-- authorisation is what was approved, and a second command for it would be a second payment for one
-- decision (docs/domain-model.md:47, 相同operation重复直接返回记录). The operation id is already unique
-- in commerce; this index is the case side's own guarantee that it never *sends* two.
CREATE TABLE case_execution_command (
    authorization_id CHAR(36)    NOT NULL,
    case_id          CHAR(36)    NOT NULL,
    operation_id     CHAR(36)    NOT NULL,
    event_id         CHAR(36)    NOT NULL,
    input_revision   BIGINT      NOT NULL,
    created_at       DATETIME(6) NOT NULL,
    PRIMARY KEY (authorization_id),
    UNIQUE KEY uq_case_execution_command_operation (operation_id),
    KEY idx_case_execution_command_case (case_id),
    CONSTRAINT fk_case_execution_command_event FOREIGN KEY (event_id) REFERENCES event_outbox (event_id),
    CONSTRAINT fk_case_execution_command_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;
