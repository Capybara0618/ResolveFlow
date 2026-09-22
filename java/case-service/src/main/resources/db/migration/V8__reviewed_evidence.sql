-- C03.2c: a human verification is its own record (docs/core-contracts.md:35: 人工核验追加，不改原材料).
--
-- A verification cites the record it verified and carries its own conclusion, and both facts live in this
-- row rather than in a queue of their own: the citation is a foreign key on (case_id, evidence_id), so "it
-- verifies a record that exists in this case" is the database's guarantee, and cross-case citations are
-- impossible rather than merely checked. There is still no update and no delete path, so the verified
-- record keeps its own text and hash and the two records stay readable side by side.
--
-- The pairing constraint allows a verification with neither member as well: the generic append route has
-- recorded free-text REVIEWER_VERIFICATION rows since C02.2a, and a CHECK that outlawed them would fail on
-- a database that already holds one. This migration is additive and does not rewrite history
-- (docs/engineering.md:64): the unbound rows keep meaning what they meant, and the structured ones are
-- distinguishable by the members they carry.

ALTER TABLE case_evidence
    ADD COLUMN reviewed_evidence_id CHAR(36) NULL AFTER question_id,
    ADD COLUMN verification_result VARCHAR(16) NULL AFTER reviewed_evidence_id,
    ADD CONSTRAINT fk_evidence_reviewed FOREIGN KEY (case_id, reviewed_evidence_id)
        REFERENCES case_evidence (case_id, evidence_id),
    ADD CONSTRAINT chk_evidence_verification_result CHECK (verification_result IS NULL
        OR verification_result IN ('CONFIRMED', 'REFUTED', 'INCONCLUSIVE')),
    ADD CONSTRAINT chk_evidence_verification_pairing CHECK (
        (reviewed_evidence_id IS NULL AND verification_result IS NULL)
        OR (source_type = 'REVIEWER_VERIFICATION' AND reviewed_evidence_id IS NOT NULL
            AND verification_result IS NOT NULL));