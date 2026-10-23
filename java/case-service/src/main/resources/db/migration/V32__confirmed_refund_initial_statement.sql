-- A chat refund's explicitly confirmed reason is part of its initial input, not a second revision.
-- Historical rows stay unchanged. Reviews and subsequent material still belong to later revisions.
ALTER TABLE case_evidence
    DROP CHECK chk_evidence_revision,
    ADD CONSTRAINT chk_evidence_revision CHECK (
        input_revision >= 2 OR (
            input_revision = 1
            AND source_type = 'CUSTOMER_STATEMENT'
            AND appended_role = 'CUSTOMER'
            AND question_id IS NULL
            AND reviewed_evidence_id IS NULL
            AND verification_result IS NULL
        )
    );
