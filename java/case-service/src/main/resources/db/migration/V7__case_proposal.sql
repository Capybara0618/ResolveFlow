-- C03.2b-2: the proposal the run submitted, and what this service made of it.
--
-- 1. A proposal is a document this service was handed, so the document is stored as it arrived
--    (payload, canonical JSON) and the outcome of the re-check is stored beside it
--    (status, recomputed_amount_minor, refusal_reason). The alternative — spreading the proposal over
--    columns and a citation child table — would mean the stored shape and the submitted shape could
--    drift, and the thing a reviewer reads back would no longer be the thing that was checked.
--
--    payload_hash is here for the same reason the callback inbox has one: it ties the stored document
--    to the delivery that produced it, so "the proposal I signed off" can be told from a later edit.
--
-- 2. status records only the re-check outcome (VALIDATED or REJECTED for the agent path; PROPOSED is
--    kept for the manual path, C03.3). STALE is *not* stored: it is a statement about the case's
--    current revision, so the read path derives it (a proposal whose input_revision is behind the
--    case's is stale) rather than an update writing the same fact every time a revision moves. A
--    stored STALE could be forgotten; a derived one cannot.
--
-- 3. sequence orders the proposals of one case. It is assigned inside the transaction that already
--    holds the case row lock, so two proposals cannot claim the same number, and the unique key makes
--    that a property of the schema rather than of the ordering of two statements.
--
-- 4. The case may carry at most one proposal that is about the current revision: the writer refuses a
--    second one for the same revision before it gets here (a run submits one terminal callback per
--    revision), so no constraint is added for it — a constraint that the code cannot violate in one
--    path but could in another is a false comfort.

CREATE TABLE case_proposal (
    proposal_id             CHAR(36)     NOT NULL,
    case_id                 CHAR(36)     NOT NULL,
    run_id                  CHAR(36)     NOT NULL,
    input_revision          BIGINT       NOT NULL,
    sequence                BIGINT       NOT NULL,
    status                  VARCHAR(16)  NOT NULL,
    recomputed_amount_minor BIGINT       NULL,
    refusal_reason          VARCHAR(500) NULL,
    payload                 JSON         NOT NULL,
    payload_hash            CHAR(64)     NOT NULL,
    created_at              DATETIME(6)  NOT NULL,
    PRIMARY KEY (proposal_id),
    UNIQUE KEY uq_case_proposal_sequence (case_id, sequence),
    KEY idx_case_proposal_case (case_id, created_at),
    CONSTRAINT fk_case_proposal_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT chk_case_proposal_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_case_proposal_sequence CHECK (sequence >= 1),
    CONSTRAINT chk_case_proposal_status CHECK (status IN ('PROPOSED', 'VALIDATED', 'STALE', 'REJECTED')),
    CONSTRAINT chk_case_proposal_amount CHECK (recomputed_amount_minor IS NULL OR recomputed_amount_minor >= 0),
    CONSTRAINT chk_case_proposal_hash CHECK (REGEXP_LIKE(payload_hash, '^[a-f0-9]{64}$')),
    -- A refusal without a reason is the answer a reviewer cannot act on, so the schema refuses it.
    CONSTRAINT chk_case_proposal_reason CHECK (
        (status <> 'REJECTED' AND refusal_reason IS NULL) OR (status = 'REJECTED' AND refusal_reason IS NOT NULL)
    )
) ENGINE = InnoDB;