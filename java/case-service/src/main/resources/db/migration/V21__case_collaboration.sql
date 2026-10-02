-- Assignment is separate from case version/input_revision and never queues an investigation.
-- Missing rows on historical cases mean unclaimed, collaboration version zero.
CREATE TABLE case_collaboration (
    case_id CHAR(36) PRIMARY KEY,
    owner_username VARCHAR(120) NULL,
    version BIGINT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_collaboration_case FOREIGN KEY (case_id) REFERENCES aftersale_case(case_id) ON DELETE CASCADE,
    CONSTRAINT fk_collaboration_owner FOREIGN KEY (owner_username) REFERENCES identity_account(username),
    CONSTRAINT ck_collaboration_version CHECK (version>=1),
    KEY ix_collaboration_owner (owner_username,case_id)
);
CREATE TABLE case_collaboration_event (
    case_id CHAR(36) NOT NULL,
    version BIGINT NOT NULL,
    action VARCHAR(16) NOT NULL,
    actor_username VARCHAR(120) NOT NULL,
    from_username VARCHAR(120) NULL,
    to_username VARCHAR(120) NULL,
    reason VARCHAR(1000) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (case_id,version),
    CONSTRAINT fk_collaboration_event_case FOREIGN KEY (case_id) REFERENCES aftersale_case(case_id) ON DELETE CASCADE,
    CONSTRAINT ck_collaboration_action CHECK (action IN ('CLAIM','RELEASE','TRANSFER','TAKEOVER'))
);
