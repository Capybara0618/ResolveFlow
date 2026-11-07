-- Preserve request hashes, observations, manifests and model snapshots verbatim.
-- The offline upgrade stages this audited map from Case before changing ownership.
CREATE TABLE IF NOT EXISTS buyer_identity_legacy (
    merchant_id text NOT NULL,
    customer_id text NOT NULL,
    buyer_id text NOT NULL,
    PRIMARY KEY (merchant_id, customer_id),
    UNIQUE (buyer_id, merchant_id)
);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='agent_run' AND column_name='customer_id') THEN
        IF EXISTS (SELECT 1 FROM agent_run r LEFT JOIN buyer_identity_legacy m
            ON r.merchant_id=m.merchant_id AND r.customer_id=m.customer_id WHERE m.buyer_id IS NULL) THEN
            RAISE EXCEPTION 'Unmapped agent run owner; stage the audited identity map before upgrading';
        END IF;
        IF EXISTS (SELECT 1 FROM agent_run WHERE status IN ('QUEUED','RUNNING'))
           OR EXISTS (SELECT 1 FROM support_agent_run WHERE status='RUNNING') THEN
            RAISE EXCEPTION 'Drain active runs with the old application before changing identity schema';
        END IF;
        UPDATE agent_run r SET customer_id=m.buyer_id FROM buyer_identity_legacy m
            WHERE r.merchant_id=m.merchant_id AND r.customer_id=m.customer_id;
        ALTER TABLE agent_run RENAME COLUMN customer_id TO buyer_id;
    END IF;
END $$;
