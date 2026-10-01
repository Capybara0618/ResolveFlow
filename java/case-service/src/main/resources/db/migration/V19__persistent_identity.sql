-- Persistent local identities. Existing usernames/subjects and tenant/customer bindings remain intact.
CREATE TABLE identity_merchant (
    merchant_id VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(120) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE identity_account (
    username VARCHAR(120) PRIMARY KEY,
    merchant_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    customer_id VARCHAR(64) NULL,
    display_name VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    identity_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_identity_merchant FOREIGN KEY (merchant_id) REFERENCES identity_merchant(merchant_id),
    CONSTRAINT ck_identity_role CHECK (role IN ('CUSTOMER','REVIEWER','MERCHANT_ADMIN','OPERATOR')),
    CONSTRAINT ck_identity_customer CHECK ((role='CUSTOMER' AND customer_id IS NOT NULL) OR (role<>'CUSTOMER' AND customer_id IS NULL)),
    CONSTRAINT ck_identity_version CHECK (identity_version>=0),
    KEY ix_identity_staff (merchant_id,role,enabled)
);
INSERT INTO identity_merchant (merchant_id,display_name) VALUES
('M-1001','ResolveFlow 演示商家一'),('M-1002','ResolveFlow 演示商家二');
INSERT INTO identity_account (username,merchant_id,role,customer_id,display_name,password_hash) VALUES
('demo-customer','M-1001','CUSTOMER','C-2002','客户 · demo-customer','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDE=$G5MeWCydEhAhLpYYPBP4JgezXRYer9cvRwsSBJu/SbU='),
('demo-customer-2','M-1001','CUSTOMER','C-2003','客户 · demo-customer-2','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDI=$8ZZCK8echvJI6B6vt4SXlZ9c/2FzjNv7g8xyLO3QXIg='),
('demo-reviewer','M-1001','REVIEWER',NULL,'审核员 · demo-reviewer','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDM=$/deceRbcZEJxA8CoJk1+KnCKigNA8zapz4qYN7AVjb0='),
('demo-customer-m2','M-1002','CUSTOMER','C-2004','客户 · demo-customer-m2','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTIwMDE=$WhNrU7h45lXeVMNJoDYbj2bhfJiqzuHg2wO3BI/UbJ4='),
('demo-reviewer-m2','M-1002','REVIEWER',NULL,'审核员 · demo-reviewer-m2','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTIwMDI=$pF6OwNSBSyYHxbbLnHcrCrgKjA8PQYSMg79rF/m8DqA='),
('demo-operator','M-1001','OPERATOR',NULL,'本地运维 · demo-operator','pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTMwMDE=$k5q+LSlQER9YsONkgU7ev/Xn2+lpOOzvEJWW9zsITX4='),
('demo-reviewer-2','M-1001','REVIEWER',NULL,'审核员 · demo-reviewer-2','pbkdf2-sha256$120000$P7JcYmz9GWkbVXy1y7Rh8w==$F0tH/+pg38HjUV0FoF7/B96AuU3iUU8x7KZbpME7gJQ='),
('demo-admin','M-1001','MERCHANT_ADMIN',NULL,'商家管理员 · demo-admin','pbkdf2-sha256$120000$rQj3VJ5hsKoU6enSLahnXw==$ueVB6Bt8Wb+bckxfjFeUc4QN79BdnENhj1vJ/edXbQ4='),
('demo-customer-m2-2','M-1002','CUSTOMER','C-2005','客户 · demo-customer-m2-2','pbkdf2-sha256$120000$YrJuYz6NZmZVYEdQw/QLog==$xB/7ZyLCW4R73cQ1AZUDK42UnmIyZK4vEP5aZcbDgzs='),
('demo-reviewer-m2-2','M-1002','REVIEWER',NULL,'审核员 · demo-reviewer-m2-2','pbkdf2-sha256$120000$AtpPm/5KOhBXdsjFdmq/Bg==$AFnCFYid2wqU7BHCTMyS/qBG+4SP880kqfrnjzflvIc='),
('demo-admin-m2','M-1002','MERCHANT_ADMIN',NULL,'商家管理员 · demo-admin-m2','pbkdf2-sha256$120000$A7xhKwHXDQWrZaCVM9qHNQ==$hxr6jlun594M/xg8v/7/EdfHyUvcGXmnQi4kMuTiFCQ=');
