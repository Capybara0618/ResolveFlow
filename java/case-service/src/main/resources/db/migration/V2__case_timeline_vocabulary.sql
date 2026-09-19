-- C02.1b: make the trajectory speak the contract's vocabulary.
--
-- V1 is already applied and is never edited (docs/engineering.md:64). Two things it could not know
-- yet, fixed forward here:
--
-- 1. case_timeline.kind used an invented spelling ('case.opened'), but the contract's
--    TimelineEventType is a closed enum whose first member is CASE_CREATED
--    (contracts/core/openapi-case.yaml). A trajectory that cannot be validated against the contract's
--    own vocabulary is a private log, not the trajectory the case view promises.
-- 2. An event needs its own identity and the input revision it belongs to: deriving either from the
--    sequence number would make an event's id change meaning as soon as the case gains revisions.

ALTER TABLE case_timeline
    ADD COLUMN event_id CHAR(36) NOT NULL DEFAULT '' AFTER case_id,
    ADD COLUMN input_revision INT NOT NULL DEFAULT 1 AFTER occurred_at;

-- Existing rows are the ones created before this migration; each gets its own id. Rows created after
-- it supply both values, which is why the temporary defaults are dropped below.
UPDATE case_timeline SET event_id = UUID() WHERE event_id = '';
UPDATE case_timeline SET kind = 'CASE_CREATED' WHERE kind = 'case.opened';

ALTER TABLE case_timeline
    ALTER COLUMN event_id DROP DEFAULT,
    ADD CONSTRAINT chk_timeline_kind CHECK (kind IN ('CASE_CREATED', 'AGENT_STARTED',
        'QUESTION_REQUIRED', 'PROPOSAL_READY', 'APPROVAL_REQUIRED', 'EXECUTION_UPDATED',
        'CASE_CLOSED')),
    ADD CONSTRAINT chk_timeline_revision CHECK (input_revision >= 1);