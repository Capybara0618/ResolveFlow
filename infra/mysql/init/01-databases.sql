-- Per-service databases and least-privilege accounts (docs/engineering.md 4:
-- "每服务独立MySQL库和最低权限账号；一台MySQL容器承载多个schema不等于共享数据权限").
--
-- One container hosting several schemas is fine; what must NOT happen is one
-- service reading another service's tables. Each account below can only touch
-- its own schema, which is what makes "Java owns its data" enforceable rather
-- than a convention.

CREATE DATABASE IF NOT EXISTS commerce_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS fulfillment_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS case_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- Local development credentials. Real environments inject these from the
-- environment; nothing here is a secret worth protecting on a dev machine.
CREATE USER IF NOT EXISTS 'commerce'@'%'    IDENTIFIED BY 'commerce';
CREATE USER IF NOT EXISTS 'fulfillment'@'%' IDENTIFIED BY 'fulfillment';
CREATE USER IF NOT EXISTS 'case_svc'@'%'    IDENTIFIED BY 'case_svc';

GRANT ALL PRIVILEGES ON commerce_db.*    TO 'commerce'@'%';
GRANT ALL PRIVILEGES ON fulfillment_db.* TO 'fulfillment'@'%';
GRANT ALL PRIVILEGES ON case_db.*        TO 'case_svc'@'%';

-- Deliberately no cross-grant: commerce cannot read case_db, and so on.

FLUSH PRIVILEGES;