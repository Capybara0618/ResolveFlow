-- C11.2b: the existing merchant/status index orders by created_at, while the
-- reviewer queue pages by updated_at DESC, case_id DESC. Keep the old index for
-- its other callers; add the exact bounded keyset access path.
CREATE INDEX idx_case_review_queue
    ON aftersale_case (merchant_id, status, updated_at DESC, case_id DESC);
