CREATE INDEX ix_case_customer_updated ON aftersale_case (merchant_id,customer_id,updated_at DESC,case_id DESC);
CREATE INDEX ix_case_customer_line ON aftersale_case (merchant_id,customer_id,line_id,updated_at DESC,case_id DESC);
