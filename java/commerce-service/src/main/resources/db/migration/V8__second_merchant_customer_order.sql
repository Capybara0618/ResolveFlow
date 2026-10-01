-- Independent synthetic order for M-1002's second customer. Existing orders, refunds and shipments stay intact.
INSERT INTO orders (order_id, merchant_id, customer_id, order_status, currency, paid_at)
VALUES ('00000000-0000-4000-8000-0000000000dd', 'M-1002', 'C-2005', 'PAID', 'CNY', '2026-09-20 08:00:00.000000');

INSERT INTO order_line (line_id, order_id, merchant_id, customer_id, sku, product_name, variant_text,
                        category, quantity, line_paid_amount, currency, paid_at, order_status, version)
VALUES ('7301', '00000000-0000-4000-8000-0000000000dd', 'M-1002', 'C-2005', 'SKU-DEMO-SHOE-38',
        '合成演示 · 轻便运动鞋', '米白 · 38码', 'footwear', 1, 22900, 'CNY', '2026-09-20 08:00:00.000000', 'PAID', 1);

INSERT INTO payment_ledger (order_id, paid_amount, refunded_amount, reserved_refund_amount, version)
VALUES ('00000000-0000-4000-8000-0000000000dd', 22900, 0, 0, 1);

INSERT INTO shipment (line_id, status, carrier_conclusion, source_version)
VALUES ('7301', 'LOST', 'LOST', 2);
INSERT INTO shipment_event (line_id, code, occurred_at, source_version)
VALUES ('7301', 'SHIPMENT_CREATED', '2026-09-20 10:00:00.000000', 1),
       ('7301', 'PARCEL_LOST', '2026-09-22 10:00:00.000000', 2);
