-- C03.3b: the decision a human made, and the rule that a case has one live authorisation at a time.
--
-- 1. The decision columns are separate from status because they answer different questions. status says
--    whether the authorisation can still be applied; decided_by/role/reason/at say who decided what and on
--    what grounds (docs/domain-model.md:31 requires the approval to record the approver, the reason and the
--    version). A reader who only had the status would know that somebody approved without knowing on what
--    grounds, and the trajectory has no actor member to fall back on.
--
-- 2. The CHECK keeps status and decision consistent in both directions: an authorisation waiting for review
--    has no decision columns, an approved/rejected/consumed one has all of them, and EXPIRED/REVOKED may go
--    either way - a supersession (C03.3c) has no human behind it, while a request for more material does,
--    and refusing to store that difference would lose who asked.
--
-- 3. live_marker is a generated column over status, with a unique key on (case_id, live_marker). MySQL
--    allows many NULLs in a unique index, so a case can accumulate any number of finished authorisations
--    while only one PENDING_REVIEW/APPROVED one can exist at a time. That is the invariant the consumption
--    boundary relies on (docs/domain-model.md:55): "the authorisation this case may execute" has to be a
--    single row, and it is enforced by the schema rather than by every writer remembering to check.

ALTER TABLE case_authorization
    ADD COLUMN decided_by      VARCHAR(64)   NULL AFTER expires_at,
    ADD COLUMN decided_role    VARCHAR(32)   NULL AFTER decided_by,
    ADD COLUMN decided_at      DATETIME(6)   NULL AFTER decided_role,
    ADD COLUMN decision_reason VARCHAR(1000) NULL AFTER decided_at,
    ADD COLUMN live_marker VARCHAR(4)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('PENDING_REVIEW', 'APPROVED') THEN 'LIVE' ELSE NULL END
        ) STORED,
    ADD UNIQUE KEY uq_authorization_live (case_id, live_marker),
    ADD CONSTRAINT chk_authorization_decided_role CHECK (
        decided_role IS NULL OR decided_role IN ('CUSTOMER', 'REVIEWER', 'OPERATOR')
    ),
    ADD CONSTRAINT chk_authorization_decision CHECK (
        (status = 'PENDING_REVIEW'
             AND decided_by IS NULL AND decided_role IS NULL
             AND decided_at IS NULL AND decision_reason IS NULL)
        OR (status IN ('APPROVED', 'REJECTED', 'CONSUMED')
             AND decided_by IS NOT NULL AND decided_role IS NOT NULL
             AND decided_at IS NOT NULL AND decision_reason IS NOT NULL)
        OR status IN ('EXPIRED', 'REVOKED')
    );

-- The trajectory vocabulary is a closed list, so it has to be maintained when the contract grows (V6 said
-- the same thing when the callback kinds arrived). AUTHORIZATION_DECIDED is the human step's second half:
-- the waiting row already existed, and a case whose authorisation was decided needs a row that says so.
ALTER TABLE case_timeline
    DROP CHECK chk_timeline_kind,
    ADD CONSTRAINT chk_timeline_kind CHECK (kind IN ('CASE_CREATED', 'EVIDENCE_APPENDED',
        'AGENT_STARTED', 'QUESTION_REQUIRED', 'PROPOSAL_READY', 'APPROVAL_REQUIRED',
        'AUTHORIZATION_DECIDED', 'EXECUTION_UPDATED', 'AGENT_FAILED', 'CASE_CLOSED'));