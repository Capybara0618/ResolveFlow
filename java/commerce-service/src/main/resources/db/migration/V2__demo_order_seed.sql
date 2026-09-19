-- C01.2b-1: the demonstration order data, for the same reason the accounts are seeded
-- (docs/product-spec.md:9: two synthetic merchants, so isolation is testable at all).
--
-- Migrations are append-only, so this seed is a migration rather than a script that has to be
-- remembered: a fresh commerce_db is immediately usable, and the read tests assert against exactly
-- these rows instead of inventing their own.
--
-- The first order and line are the ones the core OpenAPI examples use
-- (contracts/core/openapi-commerce.yaml LineContext example: order 00000000-0000-4000-8000-0000000000aa,
-- line 7001, SKU-RED-M, apparel, quantity 2, 2599 CNY, PAID, version 3), so an example in the contract
-- is a real row here. Amounts are integer minor units; times are UTC.

INSERT INTO orders (order_id, merchant_id, customer_id, order_status, currency, paid_at)
VALUES ('00000000-0000-4000-8000-0000000000aa', 'M-1001', 'C-2002', 'PAID', 'CNY', '2026-09-10 08:15:00.000000'),
       ('00000000-0000-4000-8000-0000000000bb', 'M-1001', 'C-2003', 'PAID', 'CNY', '2026-09-11 09:30:00.000000'),
       ('00000000-0000-4000-8000-0000000000cc', 'M-1002', 'C-2004', 'PAID', 'CNY', '2026-09-12 11:45:00.000000');

INSERT INTO order_line (line_id, order_id, merchant_id, customer_id, sku, category, quantity,
                        line_paid_amount, currency, paid_at, order_status, version)
VALUES ('7001', '00000000-0000-4000-8000-0000000000aa', 'M-1001', 'C-2002', 'SKU-RED-M', 'apparel', 2,
        2599, 'CNY', '2026-09-10 08:15:00.000000', 'PAID', 3),
       ('7002', '00000000-0000-4000-8000-0000000000aa', 'M-1001', 'C-2002', 'SKU-BLUE-L', 'apparel', 1,
        1999, 'CNY', '2026-09-10 08:15:00.000000', 'PAID', 1),
       ('7101', '00000000-0000-4000-8000-0000000000bb', 'M-1001', 'C-2003', 'SKU-GREEN-S', 'apparel', 1,
        1299, 'CNY', '2026-09-11 09:30:00.000000', 'PAID', 2),
       ('7201', '00000000-0000-4000-8000-0000000000cc', 'M-1002', 'C-2004', 'SKU-BOOT-42', 'footwear', 1,
        4599, 'CNY', '2026-09-12 11:45:00.000000', 'PAID', 1);

-- One ledger row per order, nothing refunded yet: the demonstration starts from a clean, fully paid
-- order, and the refund path (C05) is what moves these numbers.
INSERT INTO payment_ledger (order_id, paid_amount, refunded_amount, reserved_refund_amount, version)
VALUES ('00000000-0000-4000-8000-0000000000aa', 4598, 0, 0, 1),
       ('00000000-0000-4000-8000-0000000000bb', 1299, 0, 0, 1),
       ('00000000-0000-4000-8000-0000000000cc', 4599, 0, 0, 1);