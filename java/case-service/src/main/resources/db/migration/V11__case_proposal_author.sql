-- C03.3c-1: a proposal can be written by a person, so the row has to say who wrote it.
--
-- 1. run_id becomes nullable because a human proposal has no run, and there is no honest value to put there:
--    a sentinel run id would make every later reader believe a run existed (and the run table it would have to
--    reference is the Agent's, C06), while a nullable column says exactly what is true. The origin column is
--    what keeps that from being an implicit encoding: "run_id IS NULL" would be a second way of saying
--    "HUMAN", and this schema keeps one way.
--
-- 2. The CHECK pairs the two identities in both directions. An AGENT proposal has a run and no author; a HUMAN
--    one has an author and no run. Neither can be half-filled, because a row that is both or neither would
--    make the case view's two document shapes (contracts/core/openapi-case.yaml ProposalView) a matter of
--    guessing.
--
-- 3. Existing rows are AGENT: they were all written by the callback inbox, which only a run can post to. The
--    default fills them in the same statement that adds the column, so there is no window in which a stored
--    proposal has no origin.

ALTER TABLE case_proposal
    MODIFY COLUMN run_id CHAR(36) NULL,
    ADD COLUMN origin        VARCHAR(16) NOT NULL DEFAULT 'AGENT' AFTER run_id,
    ADD COLUMN authored_by   VARCHAR(64) NULL AFTER origin,
    ADD COLUMN authored_role VARCHAR(32) NULL AFTER authored_by,
    ADD CONSTRAINT chk_case_proposal_origin CHECK (origin IN ('AGENT', 'HUMAN')),
    ADD CONSTRAINT chk_case_proposal_author CHECK (
        (origin = 'AGENT' AND run_id IS NOT NULL AND authored_by IS NULL AND authored_role IS NULL)
        OR (origin = 'HUMAN' AND run_id IS NULL AND authored_by IS NOT NULL AND authored_role IS NOT NULL)
    ),
    ADD CONSTRAINT chk_case_proposal_authored_role CHECK (
        authored_role IS NULL OR authored_role IN ('CUSTOMER', 'REVIEWER', 'OPERATOR')
    );