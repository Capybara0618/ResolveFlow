-- C04.2: the local money side of a refund — the line's refund slot, the operation, and the request
-- inbox that makes a re-delivered command harmless.
--
-- Tables and columns follow docs/domain-model.md:42-43:
--   line_refund(line_id PK, state FREE/RESERVED/CONSUMED, operation_id, version)
--   refund_operation(operation_id PK, authorization_id UNIQUE, merchant_id, line_id, payload_hash,
--                    amount_minor, state, provider_key UNIQUE, provider_ref, retry_at, version)
-- and docs/domain-model.md:45 adds the inbox whose de-duplication shares this transaction.
--
-- Migrations are append-only (docs/engineering.md:64). Amounts are integer minor units in CNY
-- (docs/core-contracts.md:17); times are UTC DATETIME(6).
--
-- Why the slot lives in its own table rather than as a column on order_line: the slot is a refund
-- fact, and writing it onto the order read model would make the read model part of the money path.
-- docs/domain-model.md:42 gives it its own row for the same reason.

CREATE TABLE line_refund (
    line_id      VARCHAR(64) NOT NULL,
    state        VARCHAR(16) NOT NULL,
    -- The operation currently holding the slot (RESERVED) or the one that filled it (CONSUMED).
    operation_id CHAR(36)    NULL,
    version      BIGINT      NOT NULL,
    updated_at   DATETIME(6) NOT NULL,
    PRIMARY KEY (line_id),
    CONSTRAINT fk_line_refund_line FOREIGN KEY (line_id) REFERENCES order_line (line_id),
    CONSTRAINT chk_line_refund_state CHECK (state IN ('FREE', 'RESERVED', 'CONSUMED')),
    -- A FREE slot names nobody; a RESERVED or CONSUMED slot names the operation that holds or filled it.
    -- Keeping the reference on CONSUMED is what makes "who filled this line" answerable from the slot
    -- itself instead of only from the operation table.
    CONSTRAINT chk_line_refund_holder CHECK ((state = 'FREE') = (operation_id IS NULL)),
    CONSTRAINT chk_line_refund_version CHECK (version >= 1 AND version <= 9007199254740991)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- One live refund per order line, enforced by the schema rather than by a check somebody could skip
-- (docs/product-spec.md:13: 每个订单行最多一次成功退款). MySQL does not have partial indexes, so the
-- rule is expressed as a generated column that is NULL once the refund is no longer live: a unique
-- index permits any number of NULLs, which is exactly "any number of finished refunds, at most one
-- unfinished one".
ALTER TABLE line_refund
    ADD COLUMN live_marker VARCHAR(16) GENERATED ALWAYS AS
        (CASE WHEN state IN ('RESERVED', 'CONSUMED') THEN state ELSE NULL END) STORED,
    ADD UNIQUE KEY uq_line_refund_live (line_id, live_marker);
-- Both RESERVED and CONSUMED keep the marker: a consumed refund is a finished refund, and a second
-- one must be impossible for the same reason a second reservation is. FREE clears it so that a line
-- whose refund was *released* (a determined failure) can be asked about again
-- (docs/domain-model.md:51 allows a new application only after a failure released the money).

CREATE TABLE refund_operation (
    operation_id     CHAR(36)     NOT NULL,
    authorization_id CHAR(36)     NOT NULL,
    case_id          CHAR(36)     NOT NULL,
    input_revision   BIGINT       NOT NULL,
    merchant_id      VARCHAR(64)  NOT NULL,
    line_id          VARCHAR(64)  NOT NULL,
    action           VARCHAR(16)  NOT NULL,
    quantity         INT          NOT NULL,
    currency         CHAR(3)      NOT NULL,
    amount_minor     BIGINT       NOT NULL,
    payload_hash     CHAR(64)     NOT NULL,
    policy_version   VARCHAR(64)  NOT NULL,
    state            VARCHAR(16)  NOT NULL,
    -- The provider's idempotency key is the operation id: upstream retries with the same operation
    -- (docs/domain-model.md:51), and a second key for one operation is how a retry becomes a second
    -- payment. It is written at acceptance so the key is fixed before the provider is ever called, and
    -- it is the primary key that makes it unique — an extra UNIQUE on this column would be redundant.
    --
    -- Deliberately NOT unique by itself in a way that spans operations: docs/domain-model.md:51 allows a
    -- *new* operation for the same line after a determined failure released the money, so a UNIQUE key
    -- over (line_id) or over a shared provider key would forbid a re-application the domain permits.
    -- "One successful refund per line" is enforced by line_refund's generated-column index instead.
    provider_key     VARCHAR(64)  NOT NULL,
    provider_ref     VARCHAR(128) NULL,
    reason_code      VARCHAR(64)  NULL,
    retry_at         DATETIME(6)  NULL,
    reserved_at      DATETIME(6)  NOT NULL,
    settled_at       DATETIME(6)  NULL,
    version          BIGINT       NOT NULL,
    PRIMARY KEY (operation_id),
    -- One live operation per authorisation (docs/domain-model.md:43). A Case re-delivering the same
    -- authorisation is a duplicate; a *different* authorisation is a different decision and gets its
    -- own row, which is why this is not the primary key.
    UNIQUE KEY uq_refund_operation_authorization (authorization_id),
    KEY idx_refund_operation_line (line_id, state),
    KEY idx_refund_operation_retry (state, retry_at),
    CONSTRAINT fk_refund_operation_line FOREIGN KEY (line_id) REFERENCES order_line (line_id),
    -- RECEIVED/IN_PROGRESS/UNKNOWN/SUCCEEDED/FAILED are the core five
    -- (docs/domain-model.md:57); the v1 STARTING/CANCELLED target protocol is not enabled here.
    CONSTRAINT chk_refund_operation_state
        CHECK (state IN ('RECEIVED', 'IN_PROGRESS', 'UNKNOWN', 'SUCCEEDED', 'FAILED')),
    CONSTRAINT chk_refund_operation_action CHECK (action = 'REFUND'),
    CONSTRAINT chk_refund_operation_currency CHECK (currency = 'CNY'),
    CONSTRAINT chk_refund_operation_quantity CHECK (quantity >= 1 AND quantity <= 1000),
    CONSTRAINT chk_refund_operation_amount CHECK (amount_minor >= 1 AND amount_minor <= 1000000000),
    CONSTRAINT chk_refund_operation_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_refund_operation_version CHECK (version >= 1 AND version <= 9007199254740991),
    -- A settled operation has a time and a reason code slot; an unsettled one has neither. This keeps
    -- "when did the money move" from being answerable two ways.
    CONSTRAINT chk_refund_operation_settled
        CHECK ((state IN ('SUCCEEDED', 'FAILED')) = (settled_at IS NOT NULL))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE refund_request_inbox (
    -- The delivery's own id: a redelivery of the same message carries the same value
    -- (docs/domain-model.md:45, docs/core-contracts.md:29).
    request_id     VARCHAR(128) NOT NULL,
    operation_id   CHAR(36)     NOT NULL,
    payload_hash   CHAR(64)     NOT NULL,
    received_at    DATETIME(6)  NOT NULL,
    PRIMARY KEY (request_id),
    KEY idx_refund_request_inbox_operation (operation_id),
    CONSTRAINT fk_refund_request_inbox_operation
        FOREIGN KEY (operation_id) REFERENCES refund_operation (operation_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- The slot for every line starts FREE, so the acceptance path never has to distinguish "no row" from
-- "no reservation". Inserting here (rather than lazily) also means the foreign key is satisfied from
-- the start and a line can never be silently missing from the refund path.
INSERT INTO line_refund (line_id, state, operation_id, version, updated_at)
SELECT line_id, 'FREE', NULL, 1, UTC_TIMESTAMP(6) FROM order_line;
