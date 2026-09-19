-- case_db core tables (C02.1). Authority: docs/domain-model.md:22-36.
--
-- Money is not here: Case owns the case, the authorisation and the trajectory; Commerce owns orders,
-- payments and refunds (docs/architecture.md:11). Nothing in this schema duplicates a paid amount.
--
-- Migrations are append-only (docs/engineering.md:64): this file is never edited after it has run.

CREATE TABLE aftersale_case (
    case_id        CHAR(36)     NOT NULL,
    merchant_id    VARCHAR(64)  NOT NULL,
    customer_id    VARCHAR(64)  NOT NULL,
    order_id       CHAR(36)     NOT NULL,
    line_id        VARCHAR(64)  NOT NULL,
    status         VARCHAR(32)  NOT NULL,
    input_revision INT          NOT NULL,
    version        BIGINT       NOT NULL,
    -- Set when an authorisation for this case is issued (C03); null until then, rather than a
    -- placeholder date that would look like a real deadline.
    expires_at     DATETIME(6)  NULL,
    created_at     DATETIME(6)  NOT NULL,
    updated_at     DATETIME(6)  NOT NULL,
    PRIMARY KEY (case_id),
    KEY idx_case_customer (merchant_id, customer_id, created_at DESC, case_id),
    KEY idx_case_merchant (merchant_id, status, created_at DESC, case_id),
    KEY idx_case_line (merchant_id, line_id),
    -- The status set is the contract's enum (contracts/core/openapi-case.yaml), enforced where a
    -- bug cannot write past it.
    CONSTRAINT chk_case_status CHECK (status IN ('QUEUED', 'ANALYZING', 'WAITING_CUSTOMER',
        'PENDING_REVIEW', 'AUTHORIZED', 'EXECUTING', 'RECONCILING', 'CLOSED_SUCCESS',
        'CLOSED_REJECTED', 'CANCELLED')),
    CONSTRAINT chk_case_input_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_case_version CHECK (version >= 1)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- What the customer asked for. A child table rather than a JSON column, so the core's single
-- executable request can be a CHECK constraint instead of a convention.
CREATE TABLE case_requested_action (
    case_id CHAR(36)    NOT NULL,
    action  VARCHAR(32) NOT NULL,
    PRIMARY KEY (case_id, action),
    CONSTRAINT fk_case_action_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    -- Core represents only the refund request (docs/core-contracts.md:28); reship is deferred
    -- (docs/core-scope.md), so a row asking for it cannot exist even if a caller sends it.
    CONSTRAINT chk_case_action_core CHECK (action = 'REFUND')
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- One row per line that currently has an open case: the row is the lock, and it is deleted when the
-- case reaches a terminal status ("终态释放", docs/domain-model.md:26). Two open cases for one line
-- are therefore impossible by primary key, not by a check that a race could pass.
CREATE TABLE active_case_slot (
    merchant_id VARCHAR(64) NOT NULL,
    line_id     VARCHAR(64) NOT NULL,
    case_id     CHAR(36)    NOT NULL,
    created_at  DATETIME(6) NOT NULL,
    PRIMARY KEY (merchant_id, line_id),
    KEY idx_slot_case (case_id),
    CONSTRAINT fk_active_slot_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- The trajectory: appended, never rewritten (docs/domain-model.md:34, docs/core-scope.md:7).
-- detail holds canonical JSON as text, so replaying a trajectory needs no per-driver type handler.
CREATE TABLE case_timeline (
    case_id     CHAR(36)    NOT NULL,
    sequence    INT         NOT NULL,
    kind        VARCHAR(64) NOT NULL,
    detail      TEXT        NULL,
    occurred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (case_id, sequence),
    CONSTRAINT fk_timeline_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- The answer given for one idempotency key, stored as it was returned. Recomputing it later would
-- report the case's current state under an old key, which is not what was promised
-- (docs/core-contracts.md:15: same key with a different body is 409).
CREATE TABLE request_idempotency (
    merchant_id     VARCHAR(64)  NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash    CHAR(64)     NOT NULL,
    response_status INT          NOT NULL,
    response_body   TEXT         NOT NULL,
    case_id         CHAR(36)     NULL,
    created_at      DATETIME(6)  NOT NULL,
    PRIMARY KEY (merchant_id, idempotency_key),
    KEY idx_idempotency_case (case_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;