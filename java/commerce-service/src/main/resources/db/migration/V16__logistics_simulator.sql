-- Local simulation only. Append events; do not rewrite paid orders, money or old evidence.
ALTER TABLE order_fulfillment
    DROP CHECK chk_fulfillment_version,
    DROP CHECK chk_fulfillment_state,
    ADD CONSTRAINT chk_fulfillment_version CHECK (version BETWEEN 1 AND 9007199254740991),
    ADD CONSTRAINT chk_fulfillment_state CHECK (
      (status='NOT_SHIPPED' AND version=1 AND shipment_key IS NULL AND shipment_actor IS NULL AND expected_version IS NULL)
      OR (status IN ('IN_TRANSIT','DELIVERED','LOST','UNKNOWN') AND version>=2
          AND shipment_key IS NOT NULL AND shipment_actor IS NOT NULL AND expected_version=1));

CREATE TABLE shipment_simulation_fault (
    order_id VARCHAR(64) NOT NULL PRIMARY KEY,
    unavailable BOOLEAN NOT NULL,
    version BIGINT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_simulation_fault_order FOREIGN KEY (order_id) REFERENCES order_fulfillment(order_id),
    CONSTRAINT chk_simulation_fault_version CHECK (version BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE shipment_simulation_request (
    merchant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    receipt JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (merchant_id,order_id,request_key),
    CONSTRAINT fk_simulation_request_order FOREIGN KEY (order_id) REFERENCES order_fulfillment(order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Called by the local CLI, never exposed as a user HTTP route or an Agent tool.
DELIMITER $$
CREATE PROCEDURE simulate_logistics(
    IN p_order VARCHAR(64), IN p_merchant VARCHAR(64), IN p_expected BIGINT,
    IN p_scenario VARCHAR(32), IN p_key VARCHAR(128), IN p_at DATETIME(6)
)
simulator: BEGIN
    DECLARE v_status VARCHAR(16);
    DECLARE v_version BIGINT;
    DECLARE v_hash CHAR(64);
    DECLARE v_existing CHAR(64);
    DECLARE v_receipt JSON;
    DECLARE v_at DATETIME(6);
    DECLARE v_line VARCHAR(64);
    DECLARE v_line_status VARCHAR(64);
    DECLARE v_line_version BIGINT;
    DECLARE v_event_version BIGINT;
    DECLARE v_event_time DATETIME(6);
    DECLARE v_event_count INT;
    DECLARE v_line_count INT DEFAULT 0;
    DECLARE v_done BOOLEAN DEFAULT FALSE;
    DECLARE v_fault BOOLEAN;
    DECLARE v_code VARCHAR(64);
    DECLARE v_lock BIGINT;
    DECLARE line_cursor CURSOR FOR
        SELECT s.line_id,s.status,s.source_version,
               (SELECT MAX(e.source_version) FROM shipment_event e WHERE e.line_id=s.line_id),
               (SELECT MAX(e.occurred_at) FROM shipment_event e WHERE e.line_id=s.line_id),
               (SELECT COUNT(*) FROM shipment_event e WHERE e.line_id=s.line_id)
        FROM shipment s JOIN order_line l ON l.line_id=s.line_id
        WHERE l.order_id=p_order ORDER BY s.line_id FOR UPDATE;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done=TRUE;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

    IF p_order IS NULL OR p_merchant IS NULL OR p_expected IS NULL OR p_expected<2
       OR p_key IS NULL OR p_key NOT REGEXP '^[A-Za-z0-9_-]{1,128}$'
       OR p_scenario IS NULL OR p_scenario NOT IN
          ('IN_TRANSIT','DELAYED','DELIVERED','LOST','UNKNOWN','UNAVAILABLE','AVAILABLE') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid simulator arguments or not shipped';
    END IF;
    SET v_fault=p_scenario IN ('UNAVAILABLE','AVAILABLE');
    IF v_fault AND p_at IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fault switch has no logistics event time';
    END IF;
    SET v_hash=SHA2(CAST(JSON_ARRAY(p_order,p_merchant,p_expected,p_scenario,p_at) AS CHAR),256);
    SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
    START TRANSACTION;
    IF (SELECT COUNT(*) FROM orders WHERE order_id=p_order AND merchant_id=p_merchant)<>1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order ownership not found';
    END IF;
    SELECT paid_amount INTO v_lock FROM payment_ledger WHERE order_id=p_order FOR UPDATE;
    IF v_done OR (SELECT COUNT(*) FROM order_fulfillment WHERE order_id=p_order)<>1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='checkout fulfillment not found';
    END IF;
    SELECT status,version INTO v_status,v_version FROM order_fulfillment WHERE order_id=p_order FOR UPDATE;
    IF (SELECT COUNT(*) FROM shipment_simulation_request
        WHERE merchant_id=p_merchant AND order_id=p_order AND request_key=p_key)=1 THEN
        SELECT request_hash,receipt INTO v_existing,v_receipt FROM shipment_simulation_request
        WHERE merchant_id=p_merchant AND order_id=p_order AND request_key=p_key;
        IF v_hash<>v_existing THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='request key has different payload';
        END IF;
        COMMIT;
        SELECT v_receipt AS receipt;
        LEAVE simulator;
    END IF;
    IF v_version<>p_expected THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fulfillment version changed';
    END IF;
    IF v_status='NOT_SHIPPED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order must be shipped first';
    END IF;
    IF NOT v_fault AND v_status IN ('DELIVERED','LOST') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='terminal logistics cannot move backwards';
    END IF;
    IF v_version>=9007199254740991 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='version limit reached';
    END IF;
    SET v_at=COALESCE(p_at,UTC_TIMESTAMP(6));
    IF v_at>UTC_TIMESTAMP(6) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='event time is in the future';
    END IF;
    OPEN line_cursor;
    line_loop: LOOP
        FETCH line_cursor INTO v_line,v_line_status,v_line_version,v_event_version,v_event_time,v_event_count;
        IF v_done THEN LEAVE line_loop; END IF;
        SET v_line_count=v_line_count+1;
        IF v_line_status<>v_status OR v_event_version IS NULL OR v_event_version<>v_line_version
           OR v_event_time IS NULL OR v_line_version>=9007199254740991 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='inconsistent shipment history';
        END IF;
        -- First shipment uses the application clock. Allow sub-second host/container skew
        -- without rewriting history or turning an old event into a backwards update.
        IF NOT v_fault AND p_at IS NULL THEN
            IF v_event_time>UTC_TIMESTAMP(6)+INTERVAL 1 SECOND THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='source event time is ahead of database clock';
            END IF;
            SET v_at=GREATEST(v_at,v_event_time);
        END IF;
        IF NOT v_fault AND (v_at<v_event_time OR v_event_count>=200) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='event time or history limit invalid';
        END IF;
    END LOOP;
    CLOSE line_cursor;
    IF v_line_count=0 OR v_line_count<>(SELECT COUNT(*) FROM order_line WHERE order_id=p_order)
       OR EXISTS(SELECT 1 FROM order_line WHERE order_id=p_order AND merchant_id<>p_merchant) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='incomplete order shipment ownership';
    END IF;
    IF v_fault THEN
        INSERT INTO shipment_simulation_fault(order_id,unavailable,version,updated_at)
        VALUES(p_order,p_scenario='UNAVAILABLE',1,v_at)
        ON DUPLICATE KEY UPDATE unavailable=(p_scenario='UNAVAILABLE'),version=version+1,updated_at=v_at;
    ELSE
        SET v_code=CASE p_scenario WHEN 'DELAYED' THEN 'EXCEPTION_DELAYED'
                    WHEN 'UNKNOWN' THEN 'HANDOVER_UNCERTAIN' ELSE p_scenario END;
        SET v_status=IF(p_scenario='DELAYED','IN_TRANSIT',p_scenario);
        INSERT INTO shipment_event(line_id,code,occurred_at,source_version)
            SELECT s.line_id,v_code,v_at,s.source_version+1
            FROM shipment s JOIN order_line l ON l.line_id=s.line_id WHERE l.order_id=p_order;
        UPDATE shipment s JOIN order_line l ON l.line_id=s.line_id
            SET s.status=v_status,s.carrier_conclusion=v_status,s.source_version=s.source_version+1
            WHERE l.order_id=p_order;
        UPDATE order_fulfillment SET status=v_status,version=version+1,updated_at=v_at WHERE order_id=p_order;
        SET v_version=v_version+1;
    END IF;
    SET v_receipt=JSON_OBJECT('synthetic',JSON_EXTRACT('true','$'),'merchant_id',p_merchant,'order_id',p_order,
        'request_key',p_key,'scenario',p_scenario,'fulfillment_version',v_version,
        'status',v_status,'affected_lines',v_line_count,'recorded_at',DATE_FORMAT(v_at,'%Y-%m-%dT%H:%i:%s.%fZ'),
        'query_unavailable',COALESCE((SELECT unavailable FROM shipment_simulation_fault WHERE order_id=p_order),FALSE),
        'line_versions',(SELECT JSON_ARRAYAGG(JSON_OBJECT('line_id',s.line_id,'source_version',s.source_version))
                         FROM shipment s JOIN order_line l ON l.line_id=s.line_id WHERE l.order_id=p_order));
    INSERT INTO shipment_simulation_request(merchant_id,order_id,request_key,request_hash,receipt,created_at)
        VALUES(p_merchant,p_order,p_key,v_hash,v_receipt,UTC_TIMESTAMP(6));
    COMMIT;
    SELECT v_receipt AS receipt;
END$$
DELIMITER ;
