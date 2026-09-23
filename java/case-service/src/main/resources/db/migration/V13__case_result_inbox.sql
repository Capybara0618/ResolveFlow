-- C05.2b-3a: case-service's inbox for signed refund results.
--
-- Commerce now signs its results (C05.2b-1) and publishes them at least once (C05.2b-2), so this service
-- *will* see redeliveries. This table is what makes a redelivery harmless: the row is the claim, and the claim
-- and the recorded fact are written in one transaction (docs/domain-model.md:45), so a second delivery finds
-- the claim and stops instead of storing a second copy of the same fact.
--
-- The primary key is (consumer, event_id) rather than event_id alone, for the reason Commerce's inbox states
-- from the other side (V4__commerce_event_inbox.sql): one event can legitimately concern more than one
-- consumer, and a single-column key would make the second reader see the first reader's row and skip its work.
-- Today this service has exactly one result consumer, so the column is a name rather than a routing table.
--
-- Why the raw envelope and signature are stored verbatim: verification happened against the exact bytes that
-- arrived, and re-deriving the document later would verify whatever the code looks like then rather than what
-- Commerce signed. A LONGTEXT rather than a JSON column for the same reason as the outbox: a JSON column is
-- free to reformat, and a reformatted document is no longer the byte sequence the signature covered.
--
-- Why the payload members are copied out as columns: they are the parsed facts the projection (C05.2b-3b) and
-- an operator will read. `aggregate_version` is Commerce's optimistic-lock version of the operation — used for
-- out-of-order detection, never as this case's input revision (contracts/core/event-envelope.schema.json).
--
-- Migrations are append-only (docs/engineering.md:64).

CREATE TABLE case_result_inbox (
    consumer          VARCHAR(64)  NOT NULL,
    -- The producer's own event id, stable across redeliveries: that is the whole point of claiming it.
    event_id          CHAR(36)     NOT NULL,
    event_type        VARCHAR(32)  NOT NULL,
    schema_version    INT          NOT NULL,
    merchant_id       VARCHAR(64)  NOT NULL,
    -- The case the result belongs to, resolved from the operation this service issued (case_execution_command)
    -- rather than taken from the message: the message names an operation, and Case owns the operation-to-case
    -- mapping.
    case_id           CHAR(36)     NOT NULL,
    operation_id      CHAR(36)     NOT NULL,
    line_id           VARCHAR(64)  NOT NULL,
    state             VARCHAR(16)  NOT NULL,
    amount_minor      BIGINT       NOT NULL,
    provider_ref      VARCHAR(200) NULL,
    reason_code       VARCHAR(64)  NULL,
    aggregate_version BIGINT       NOT NULL,
    envelope          LONGTEXT     NOT NULL,
    -- The signature is inside `envelope` too; this column exists so an operator can see at a glance that a row
    -- is signed without parsing JSON, and so a later migration can index on it if a trust list changes.
    signature         VARCHAR(128) NOT NULL,
    signing_key_id    VARCHAR(64)  NOT NULL,
    -- What the first delivery of this event was: always ACCEPTED, because the insert *is* the claim and a row
    -- only exists once the deciding transaction has decided. It is not rewritten by a redelivery, so the row
    -- keeps saying that the event was accepted the first time; a redelivery is visible in `detail` instead.
    disposition       VARCHAR(16)  NOT NULL,
    -- The sentence a person reads about the latest delivery, written by the claim statement itself: a claim
    -- leaves it NULL, a redelivery sets it to 'duplicate delivery ignored'.
    detail            VARCHAR(500) NULL,
    received_at       DATETIME(6)  NOT NULL,
    -- The marker C05.2b-3b consumes: unset until the result has been projected onto the case state machine
    -- (docs/core-contracts.md:86 keeps the inbox row, the projection and the local timeline in one
    -- transaction). This sub-step never sets it, and the boundary test asserts exactly that.
    projected_at      DATETIME(6)  NULL,
    PRIMARY KEY (consumer, event_id),
    KEY idx_case_result_inbox_case (case_id, received_at),
    KEY idx_case_result_inbox_unprojected (projected_at, received_at),
    KEY idx_case_result_inbox_operation (operation_id, aggregate_version),
    CONSTRAINT fk_case_result_inbox_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT chk_case_result_inbox_schema_version CHECK (schema_version = 2),
    CONSTRAINT chk_case_result_inbox_state CHECK (state IN ('SUCCEEDED', 'FAILED', 'UNKNOWN')),
    CONSTRAINT chk_case_result_inbox_disposition CHECK (disposition IN ('ACCEPTED', 'DUPLICATE')),
    CONSTRAINT chk_case_result_inbox_amount CHECK (amount_minor >= 1 AND amount_minor <= 1000000000),
    CONSTRAINT chk_case_result_inbox_aggregate_version CHECK (aggregate_version >= 1),
    -- A DUPLICATE row can never be projected: only the delivery that claimed the event may project it, and the
    -- claim writes ACCEPTED. Stated here rather than left to a reader, because "projected twice" is exactly the
    -- kind of duplicate this table exists to make impossible.
    CONSTRAINT chk_case_result_inbox_projected
        CHECK ((disposition = 'ACCEPTED') OR (projected_at IS NULL))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- Every refused result is kept, with why. A refused result is not noise: "this arrived and I would not act on
-- it" is what an operator needs when a refund is missing, and a consumer that only logged it to stdout would
-- have thrown the evidence away. Separate from the inbox because a refused message must survive the consumer's
-- rollback, which is why it is written in its own transaction (CaseResultRejectionLog).
CREATE TABLE case_result_rejection (
    rejection_id CHAR(36)     NOT NULL,
    consumer     VARCHAR(64)  NOT NULL,
    event_id     CHAR(36)     NULL,
    topic        VARCHAR(64)  NULL,
    reason       VARCHAR(32)  NOT NULL,
    detail       VARCHAR(500) NOT NULL,
    raw_message  LONGTEXT     NULL,
    received_at  DATETIME(6)  NOT NULL,
    PRIMARY KEY (rejection_id),
    KEY idx_case_result_rejection_received (received_at),
    KEY idx_case_result_rejection_reason (reason, received_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;