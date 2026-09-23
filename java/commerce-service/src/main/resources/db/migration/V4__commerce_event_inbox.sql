-- C05.1b: commerce-service's inbox for core events.
--
-- The command arrives over an at-least-once transport, so the consumer *will* see duplicates: a publish whose
-- acknowledgement was lost is indistinguishable from one that never arrived (OutboxDeliveryService says the
-- same thing from the other side). This table is what makes a duplicate harmless — the row and the business
-- effect are written in one transaction (docs/domain-model.md:45), so a redelivery finds the claim and stops.
--
-- The key is (consumer, event_id), not event_id alone: the same event legitimately concerns more than one
-- consumer (a result event is read by Commerce's reconciler and projected by Case), and a single-column key
-- would make the second reader see the first reader's row and skip its own work.
--
-- Migrations are append-only (docs/engineering.md:64).
CREATE TABLE event_inbox (
    consumer     VARCHAR(64) NOT NULL,
    -- The producer's own event id, which is stable across redeliveries: that is the whole point.
    event_id     CHAR(36)    NOT NULL,
    event_type   VARCHAR(32) NOT NULL,
    producer     VARCHAR(32) NOT NULL,
    -- What this consumer did with it. APPLIED and IGNORED are both terminal records; a row is only written
    -- once the deciding transaction has decided.
    disposition  VARCHAR(16) NOT NULL,
    detail       VARCHAR(500) NULL,
    received_at  DATETIME(6) NOT NULL,
    PRIMARY KEY (consumer, event_id),
    KEY idx_event_inbox_received (received_at),
    KEY idx_event_inbox_type (event_type, received_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- Every refused message is kept, with why. A rejected command is not noise: "this arrived and I would not
-- execute it" is what an operator needs when a refund is missing, and a consumer that only logged it to
-- stdout would have thrown the evidence away.
CREATE TABLE event_rejection (
    rejection_id CHAR(36)     NOT NULL,
    consumer     VARCHAR(64)  NOT NULL,
    event_id     CHAR(36)     NULL,
    topic        VARCHAR(64)  NULL,
    reason       VARCHAR(32)  NOT NULL,
    detail       VARCHAR(500) NOT NULL,
    raw_message  LONGTEXT     NULL,
    received_at  DATETIME(6)  NOT NULL,
    PRIMARY KEY (rejection_id),
    KEY idx_event_rejection_received (received_at),
    KEY idx_event_rejection_reason (reason, received_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;
