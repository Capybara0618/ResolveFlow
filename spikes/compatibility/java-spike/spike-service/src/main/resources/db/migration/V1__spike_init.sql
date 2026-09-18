-- T00 compatibility spike schema (temporary; not the production migration set).
-- Mirrors the mechanics that the real money invariants depend on:
--   INV-01 refunded + reserved <= paid, all non-negative  -> conditional UPDATE + CHECK
--   INV-02 at most one active remedy entitlement per line -> row lock + state CAS
-- Money is BIGINT minor units. Never float/double.

CREATE TABLE orders (
    id          BIGINT       NOT NULL,
    merchant_id BIGINT       NOT NULL,
    customer_id BIGINT       NOT NULL,
    status      VARCHAR(32)  NOT NULL,
    version     BIGINT       NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
) ENGINE = InnoDB;

CREATE TABLE order_line (
    id                BIGINT      NOT NULL,
    order_id          BIGINT      NOT NULL,
    sku               VARCHAR(64) NOT NULL,
    quantity          INT         NOT NULL,
    line_paid_amount  BIGINT      NOT NULL,
    currency          CHAR(3)     NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_line_order FOREIGN KEY (order_id) REFERENCES orders (id),
    CONSTRAINT ck_line_paid_nonneg CHECK (line_paid_amount >= 0),
    CONSTRAINT ck_line_qty_pos CHECK (quantity > 0)
) ENGINE = InnoDB;

-- One ledger row per order; refund reservations use a conditional UPDATE so the
-- balance can never be oversubscribed under concurrency.
CREATE TABLE payment_ledger (
    order_id                BIGINT   NOT NULL,
    paid_amount             BIGINT   NOT NULL,
    refunded_amount         BIGINT   NOT NULL DEFAULT 0,
    reserved_refund_amount  BIGINT   NOT NULL DEFAULT 0,
    version                 BIGINT   NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id),
    CONSTRAINT fk_ledger_order FOREIGN KEY (order_id) REFERENCES orders (id),
    CONSTRAINT ck_ledger_nonneg CHECK (
        paid_amount >= 0 AND refunded_amount >= 0 AND reserved_refund_amount >= 0
    ),
    CONSTRAINT ck_ledger_within_paid CHECK (
        refunded_amount + reserved_refund_amount <= paid_amount
    )
) ENGINE = InnoDB;

-- REFUND and RESHIP share this row, which is what makes them mutually exclusive.
CREATE TABLE line_entitlement (
    line_id      BIGINT      NOT NULL,
    merchant_id  BIGINT      NOT NULL,
    action       VARCHAR(16) NOT NULL,
    operation_id CHAR(36)    NULL,
    state        VARCHAR(16) NOT NULL,
    version      BIGINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (line_id),
    CONSTRAINT fk_entitlement_line FOREIGN KEY (line_id) REFERENCES order_line (id),
    CONSTRAINT ck_entitlement_state CHECK (state IN ('FREE', 'RESERVED', 'IN_USE', 'CONSUMED')),
    CONSTRAINT ck_entitlement_action CHECK (action IN ('NONE', 'REFUND', 'RESHIP'))
) ENGINE = InnoDB;

-- History so a released operation keeps its idempotent result and a stale
-- operation can never re-occupy the line.
CREATE TABLE entitlement_operation (
    operation_id CHAR(36)    NOT NULL,
    line_id      BIGINT      NOT NULL,
    action       VARCHAR(16) NOT NULL,
    state        VARCHAR(16) NOT NULL,
    PRIMARY KEY (operation_id)
) ENGINE = InnoDB;