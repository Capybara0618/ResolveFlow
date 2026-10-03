-- Independent paid synthetic samples for the newly created buyer. Not evidence of a shopping checkout.
INSERT INTO orders (order_id,merchant_id,customer_id,order_status,currency,paid_at) VALUES
('00000000-0000-4000-8000-000000003001','M-1001','C-B3001-M1001','PAID','CNY','2026-09-20 08:00:00.123456'),
('00000000-0000-4000-8000-000000003002','M-1002','C-B3001-M1002','PAID','CNY','2026-09-20 08:00:00.123457');
INSERT INTO order_line (line_id,order_id,merchant_id,customer_id,sku,product_name,variant_text,category,quantity,
                       line_paid_amount,currency,paid_at,order_status,version) VALUES
('BUYER-3001-A','00000000-0000-4000-8000-000000003001','M-1001','C-B3001-M1001','M1-HEADPHONE',
 '合成演示 · 无线降噪耳机','黑色','electronics',1,32900,'CNY','2026-09-20 08:00:00.123456','PAID',1),
('BUYER-3001-B','00000000-0000-4000-8000-000000003002','M-1002','C-B3001-M1002','M2-LAMP',
 '合成演示 · 护眼台灯','白色','home',1,12900,'CNY','2026-09-20 08:00:00.123457','PAID',1);
INSERT INTO payment_ledger (order_id,paid_amount,refunded_amount,reserved_refund_amount,version) VALUES
('00000000-0000-4000-8000-000000003001',32900,0,0,1),
('00000000-0000-4000-8000-000000003002',12900,0,0,1);
INSERT INTO line_refund (line_id,state,operation_id,version,updated_at) VALUES
('BUYER-3001-A','FREE',NULL,1,'2026-09-20 08:00:00.123456'),
('BUYER-3001-B','FREE',NULL,1,'2026-09-20 08:00:00.123457');
INSERT INTO shipment (line_id,status,carrier_conclusion,source_version) VALUES
('BUYER-3001-A','LOST','LOST',2),('BUYER-3001-B','LOST','LOST',2);
INSERT INTO shipment_event (line_id,code,occurred_at,source_version) VALUES
('BUYER-3001-A','SHIPMENT_CREATED','2026-09-20 10:00:00',1),
('BUYER-3001-A','PARCEL_LOST','2026-09-22 10:00:00',2),
('BUYER-3001-B','SHIPMENT_CREATED','2026-09-20 10:00:00',1),
('BUYER-3001-B','PARCEL_LOST','2026-09-22 10:00:00',2);
