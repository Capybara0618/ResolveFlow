-- C05.2b-3a review fix (2026-09-23): the claim's duplicate branch has to change the row.
--
-- `INSERT ... ON DUPLICATE KEY UPDATE detail = 'duplicate delivery ignored'` answers "2 = already claimed" only
-- for the *first* redelivery. After that, `detail` already holds that sentence, the update changes nothing, and
-- MySQL then reports 0 affected rows — or 1 under Connector/J's default (`useAffectedRows=false` sets
-- CLIENT_FOUND_ROWS), which the consumer reads as "a fresh claim". A third delivery of the same result was
-- therefore reported as ACCEPTED instead of DUPLICATE. That is not a theoretical difference: it was observed in
-- the third-delivery test's red run, which is kept in reports/c052b3a-result-inbox/.
--
-- `deliveries` makes every redelivery change the row, so the affected-row count is deterministic under either
-- convention (1 = this delivery claimed it, 2 = it was already claimed) and an operator gets the delivery count
-- as a fact rather than an inference.
--
-- Append-only: V13 is not edited, because it may already have been applied elsewhere and Flyway checksums its
-- text (docs/engineering.md:64).
ALTER TABLE case_result_inbox
    ADD COLUMN deliveries INT NOT NULL DEFAULT 1 AFTER detail,
    ADD CONSTRAINT chk_case_result_inbox_deliveries CHECK (deliveries >= 1);