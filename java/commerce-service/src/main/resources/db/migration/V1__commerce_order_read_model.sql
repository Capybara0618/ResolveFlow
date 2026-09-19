-- C01.2b-1: commerce_db's order read model.
--
-- Tables and columns follow docs/domain-model.md:40-41 (orders/order_line: ownership, paid time,
-- original line amount/quantity/category; payment_ledger(order_id PK, paid_amount,
-- refunded_amount, reserved_refund_amount, version)) and docs/architecture.md:11 (commerce_db owns
-- orders and payments).
--
-- Migrations are append-only (docs/engineering.md:64): this file is never edited once applied.
--
-- Amounts are integer minor units in CNY, never floats (docs/core-contracts.md:17). Time is stored
-- as UTC DATETIME(6); the driver is pinned to UTC so no reader has to guess a zone.
--
-- coherence: only whole, unrefunded orders enter the core flow, so the seed below has no partially
-- refunded order. A partially refunded order is not a case for this protocol (docs/domain-model.md:40);
-- the gate that refuses to open a case on one belongs to the case lifecycle (C02/C06), and the
-- ledger amounts here exist so that gate has an authoritative source to read.

CREATE TABLE orders (
    order_id      CHAR(36)     NOT NULL,
    merchant_id   VARCHAR(64)  NOT NULL,
    customer_id   VARCHAR(64)  NOT NULL,
    order_status  VARCHAR(32)  NOT NULL,
    currency      CHAR(3)      NOT NULL,
    paid_at       DATETIME(6)  NOT NULL,
    created_at    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (order_id),
    KEY idx_orders_scope (merchant_id, customer_id, paid_at DESC, order_id),
    CONSTRAINT chk_orders_currency CHECK (currency = 'CNY')
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE order_line (
    line_id           VARCHAR(64)  NOT NULL,
    order_id          CHAR(36)     NOT NULL,
    merchant_id       VARCHAR(64)  NOT NULL,
    customer_id       VARCHAR(64)  NOT NULL,
    sku               VARCHAR(64)  NOT NULL,
    category          VARCHAR(64)  NOT NULL,
    quantity          INT          NOT NULL,
    line_paid_amount  BIGINT       NOT NULL,
    currency          CHAR(3)      NOT NULL,
    paid_at           DATETIME(6)  NOT NULL,
    order_status      VARCHAR(32)  NOT NULL,
    version           BIGINT       NOT NULL,
    PRIMARY KEY (line_id),
    -- The listing route reads by (merchant, customer?) ordered by paid_at+line_id: keyset order,
    -- so the index carries the same order and the query never needs a filesort or an offset.
    KEY idx_order_line_scope (merchant_id, customer_id, paid_at DESC, line_id DESC),
    CONSTRAINT fk_order_line_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
    CONSTRAINT chk_order_line_quantity CHECK (quantity >= 1 AND quantity <= 1000),
    CONSTRAINT chk_order_line_amount CHECK (line_paid_amount >= 0),
    CONSTRAINT chk_order_line_currency CHECK (currency = 'CNY'),
    CONSTRAINT chk_order_line_version CHECK (version >= 1 AND version <= 9007199254740991)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE payment_ledger (
    order_id                CHAR(36)  NOT NULL,
    paid_amount             BIGINT    NOT NULL,
    refunded_amount         BIGINT    NOT NULL DEFAULT 0,
    reserved_refund_amount  BIGINT    NOT NULL DEFAULT 0,
    version                 BIGINT    NOT NULL,
    PRIMARY KEY (order_id),
    CONSTRAINT fk_payment_ledger_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
    -- 订单已退+预留不超过支付额 (docs/domain-model.md:41, docs/product-spec.md:13). The refund
    -- path locks this row before it reserves, so the constraint is the last line of defence rather
    -- than the only one.
    CONSTRAINT chk_payment_ledger_within_paid
        CHECK (paid_amount >= 0 AND refunded_amount >= 0 AND reserved_refund_amount >= 0
            AND refunded_amount + reserved_refund_amount <= paid_amount),
    CONSTRAINT chk_payment_ledger_version CHECK (version >= 1 AND version <= 9007199254740991)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;