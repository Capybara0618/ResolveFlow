-- Append-only: retrieval children do not replace Java's complete-rule citation rows.
ALTER TABLE policy_index_generation
    ADD COLUMN IF NOT EXISTS retrieval_layout text NOT NULL DEFAULT 'whole-rule-v1',
    ADD COLUMN IF NOT EXISTS child_count integer NOT NULL DEFAULT 0 CHECK (child_count >= 0),
    ADD COLUMN IF NOT EXISTS retrieval_fingerprint text;

CREATE TABLE IF NOT EXISTS policy_index_child (
    generation_id text NOT NULL,
    bundle_id text NOT NULL,
    child_id text NOT NULL,
    parent_chunk_id text NOT NULL,
    start_offset integer NOT NULL CHECK (start_offset >= 0),
    end_offset integer NOT NULL CHECK (end_offset > start_offset),
    encoder_tokens integer NOT NULL CHECK (encoder_tokens >= 3),
    text text NOT NULL,
    text_sha256 text NOT NULL CHECK (text_sha256 ~ '^[a-f0-9]{64}$'),
    embedding real[] NOT NULL,
    PRIMARY KEY (generation_id, bundle_id, child_id),
    FOREIGN KEY (generation_id, bundle_id, parent_chunk_id)
        REFERENCES policy_index_chunk (generation_id, bundle_id, chunk_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_policy_child_parent
    ON policy_index_child (generation_id, bundle_id, parent_chunk_id, start_offset);
