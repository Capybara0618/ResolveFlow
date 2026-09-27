-- Isolated, repeatable C11 review-queue dataset. Never clears case_db or shared data.
CREATE DATABASE IF NOT EXISTS c11_review_bench;
CREATE TABLE IF NOT EXISTS c11_review_bench.aftersale_case LIKE case_db.aftersale_case;

INSERT IGNORE INTO c11_review_bench.aftersale_case
    (case_id, merchant_id, customer_id, order_id, line_id, status,
     input_revision, version, created_at, updated_at, description)
SELECT CONCAT('00000000-0000-4000-8000-', LPAD(n + merchant.i * 10000, 12, '0')),
       IF(merchant.i = 0, 'M-1001', 'M-2002'),
       CONCAT('C-', LPAD(MOD(n, 200), 4, '0')),
       CONCAT('10000000-0000-4000-8000-', LPAD(n + merchant.i * 10000, 12, '0')),
       CONCAT('bench-', LPAD(n + merchant.i * 10000, 5, '0')),
       IF(MOD(n, 5) = 0, 'PENDING_REVIEW', 'QUEUED'),
       1, 1,
       DATE_ADD('2026-09-01 00:00:00', INTERVAL (10000 - n) SECOND),
       DATE_ADD('2026-09-01 00:00:00', INTERVAL n SECOND),
       'SYNTHETIC_C11_REVIEW_BENCH'
FROM (
    SELECT a.i + b.i * 10 + c.i * 100 + d.i * 1000 AS n
    FROM (SELECT 0 i UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
          UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) a
    CROSS JOIN (SELECT 0 i UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) b
    CROSS JOIN (SELECT 0 i UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) c
    CROSS JOIN (SELECT 0 i UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) d
) numbers
CROSS JOIN (SELECT 0 i UNION ALL SELECT 1) merchant;

ANALYZE TABLE c11_review_bench.aftersale_case;
SELECT COUNT(*) AS total_rows,
       SUM(status = 'PENDING_REVIEW') AS review_rows,
       COUNT(DISTINCT merchant_id) AS merchants
FROM c11_review_bench.aftersale_case;
