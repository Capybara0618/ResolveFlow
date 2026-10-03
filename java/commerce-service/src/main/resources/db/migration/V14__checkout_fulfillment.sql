-- Only checkout-published, paid orders gain an explicit local unshipped fact.
-- Historical carrier stories and money/cases are never rewritten.
CREATE TABLE order_fulfillment (
    order_id VARCHAR(64) NOT NULL PRIMARY KEY,
    status VARCHAR(16) NOT NULL,
    version BIGINT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    shipment_key VARCHAR(128) NULL,
    shipment_actor VARCHAR(128) NULL,
    expected_version BIGINT NULL,
    CONSTRAINT fk_fulfillment_order FOREIGN KEY (order_id) REFERENCES orders(order_id),
    CONSTRAINT chk_fulfillment_version CHECK (version IN (1,2)),
    CONSTRAINT chk_fulfillment_state CHECK (
      (status='NOT_SHIPPED' AND version=1 AND shipment_key IS NULL AND shipment_actor IS NULL AND expected_version IS NULL)
      OR (status='IN_TRANSIT' AND version=2 AND shipment_key IS NOT NULL AND shipment_actor IS NOT NULL AND expected_version=1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO order_fulfillment(order_id,status,version,updated_at)
SELECT o.order_id,'NOT_SHIPPED',1,o.paid_at FROM orders o
WHERE o.paid_at IS NOT NULL AND EXISTS (SELECT 1 FROM checkout_draft d WHERE d.order_id=o.order_id AND d.status='PAID')
AND EXISTS(SELECT 1 FROM order_line l WHERE l.order_id=o.order_id)
AND NOT EXISTS(SELECT 1 FROM order_line l JOIN shipment s ON s.line_id=l.line_id WHERE l.order_id=o.order_id);

INSERT INTO shipment(line_id,status,carrier_conclusion,source_version)
SELECT l.line_id,'NOT_SHIPPED','UNKNOWN',1 FROM order_line l JOIN order_fulfillment f ON f.order_id=l.order_id;
INSERT INTO shipment_event(line_id,code,occurred_at,source_version)
SELECT l.line_id,'ORDER_PAID',f.updated_at,1 FROM order_line l JOIN order_fulfillment f ON f.order_id=l.order_id;
