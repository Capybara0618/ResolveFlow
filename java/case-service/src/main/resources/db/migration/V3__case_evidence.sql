-- C02.2a: customer material (docs/domain-model.md:27: 来源、ref、version、hash、revision、observed_at、
-- 内容；追加而非覆盖).
--
-- Appending is the only write: there is no update path and no delete path in the code, so "material is
-- never overwritten" is a property of the schema's use rather than of a check somebody could forget.
-- Each row carries the revision it belongs to, and the revision is the server's — the request body has
-- no revision member, so material cannot be written into a past revision.

CREATE TABLE case_evidence (
    case_id        CHAR(36)     NOT NULL,
    evidence_id    CHAR(36)     NOT NULL,
    source_type    VARCHAR(32)  NOT NULL,
    source_ref     VARCHAR(255) NOT NULL,
    source_version VARCHAR(64)  NOT NULL,
    content_hash   CHAR(64)     NOT NULL,
    -- The input revision this material belongs to. Revision 1 is the case's creation, which has no
    -- material, so every row here is at least 2: material always arrives after the case exists.
    input_revision INT          NOT NULL,
    observed_at    DATETIME(6)  NOT NULL,
    content        TEXT         NOT NULL,
    question_id    VARCHAR(64)  NULL,
    appended_by    VARCHAR(64)  NOT NULL,
    appended_role  VARCHAR(32)  NOT NULL,
    created_at     DATETIME(6)  NOT NULL,
    PRIMARY KEY (case_id, evidence_id),
    KEY idx_evidence_revision (case_id, input_revision, created_at, evidence_id),
    CONSTRAINT fk_evidence_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    -- The source vocabulary is the contract's EvidenceSourceType enum, enforced where a bug cannot
    -- write past it. Which of these a *client* may submit is a route rule (403), not a schema rule:
    -- the investigation reads carrier and ledger facts through its own path (C06).
    CONSTRAINT chk_evidence_source CHECK (source_type IN ('ORDER_LINE', 'PAYMENT_LEDGER', 'SHIPMENT',
        'SHIPMENT_TRACK', 'CUSTOMER_STATEMENT', 'REVIEWER_VERIFICATION', 'POLICY_RULE')),
    CONSTRAINT chk_evidence_revision CHECK (input_revision >= 2),
    CONSTRAINT chk_evidence_appended_role CHECK (appended_role IN ('CUSTOMER', 'REVIEWER', 'OPERATOR'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- The trajectory gains the member that explains a moved revision (contracts/core/openapi-case.yaml).
-- V2's constraint was a closed list of the enum as it stood then; extending it is the append-only way
-- to add a value, and it is done here rather than by editing V2 (docs/engineering.md:64).
ALTER TABLE case_timeline
    DROP CHECK chk_timeline_kind,
    ADD CONSTRAINT chk_timeline_kind CHECK (kind IN ('CASE_CREATED', 'EVIDENCE_APPENDED',
        'AGENT_STARTED', 'QUESTION_REQUIRED', 'PROPOSAL_READY', 'APPROVAL_REQUIRED',
        'EXECUTION_UPDATED', 'CASE_CLOSED'));