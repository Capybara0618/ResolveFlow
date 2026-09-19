-- C03.2b-1: the callback inbox, and the trajectory learning to say that a run failed.
--
-- 1. chk_timeline_kind is a closed list of the enum as it stood when it was written. The contract now has
--    AGENT_FAILED, because an accepted FAILED callback has to be visible: the investigation ended without
--    a question and without a proposal, and a case that showed nothing would look like a run that is still
--    thinking. Extending the list forward is the append-only way of changing it (docs/engineering.md:64);
--    V3 already did the same for EVIDENCE_APPENDED.
--
-- 2. agent_callback is the delivery record, and callback_id is its primary key. That is what makes
--    "applied at most once" a property of the schema instead of a check somebody could race: the insert is
--    the claim, so two deliveries arriving together cannot both pass it, and the loser is told DUPLICATE.
--    payload_hash is stored next to it so a genuine redelivery and "same callback_id, different content"
--    can be told apart — the second is not a redelivery, it is a broken producer.
--
--    The disposition column holds ACCEPTED or STALE, never DUPLICATE: a duplicate is an answer about a
--    delivery that was already recorded, so storing it would mean writing a second row for the same
--    callback_id, which the primary key refuses anyway.
--
--    The payload itself is not stored here. What has to be durable is that this delivery happened and
--    what it did; the facts of a proposal are kept in their own table (C03.2b-2), and copying every
--    payload into this one would create a second, unread copy of them.

ALTER TABLE case_timeline
    DROP CHECK chk_timeline_kind,
    ADD CONSTRAINT chk_timeline_kind CHECK (kind IN ('CASE_CREATED', 'EVIDENCE_APPENDED',
        'AGENT_STARTED', 'QUESTION_REQUIRED', 'PROPOSAL_READY', 'APPROVAL_REQUIRED',
        'EXECUTION_UPDATED', 'AGENT_FAILED', 'CASE_CLOSED'));

CREATE TABLE agent_callback (
    callback_id    VARCHAR(64)  NOT NULL,
    case_id        CHAR(36)     NOT NULL,
    run_id         CHAR(36)     NOT NULL,
    input_revision BIGINT       NOT NULL,
    kind           VARCHAR(16)  NOT NULL,
    disposition    VARCHAR(16)  NOT NULL,
    payload_hash   CHAR(64)     NOT NULL,
    traceparent    VARCHAR(64)  NULL,
    received_at    DATETIME(6)  NOT NULL,
    PRIMARY KEY (callback_id),
    CONSTRAINT fk_agent_callback_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT chk_agent_callback_kind
        CHECK (kind IN ('STARTED', 'QUESTION', 'PROPOSAL', 'FAILED')),
    CONSTRAINT chk_agent_callback_disposition CHECK (disposition IN ('ACCEPTED', 'STALE')),
    CONSTRAINT chk_agent_callback_revision CHECK (input_revision >= 1),
    CONSTRAINT chk_agent_callback_hash CHECK (payload_hash REGEXP '^[a-f0-9]{64}$'),
    CONSTRAINT chk_agent_callback_traceparent
        CHECK (traceparent IS NULL OR traceparent REGEXP '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
    INDEX idx_agent_callback_case (case_id, received_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;