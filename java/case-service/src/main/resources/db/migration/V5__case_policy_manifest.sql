-- C03.1b: the policy manifest a case is pinned to (docs/core-contracts.md:50).
--
-- "A run is pinned to an immutable manifest; a case never silently switches to a newer policy." That
-- sentence is the reason this table exists: the bundle a case was opened under is chosen once, by the
-- line's payment time, and stored. Importing a newer policy afterwards changes nothing about a case that
-- is already open, which is exactly the property a historical order needs.
--
-- The window is stored on the case rather than read from policy_bundle at read time. Two reasons, both
-- about honesty: the selection has to stay explainable even if the bundle row is later removed, and the
-- window is what *made* the selection — a reader asking "why this policy" gets the answer from the case
-- itself. The hash is stored for the same reason the bundle stores one: a citation checked later is
-- checked against the text whose hash is recorded here.
--
-- One row per case, and the bundles are a child table because the contract's manifest is a list of bundle
-- sets (bundles[].bundle_ids). Core selects exactly one bundle today; the shape does not pretend otherwise,
-- and a second family (for example a safety policy) would be a row, not a schema change.

CREATE TABLE case_policy_manifest (
    case_id             CHAR(36)    NOT NULL,
    manifest_hash       CHAR(64)    NOT NULL,
    safety_epoch        INT         NOT NULL,
    effective_from      DATETIME(6) NOT NULL,
    effective_to        DATETIME(6) NULL,
    -- The instant the version was chosen by, kept so "why this version" is answerable from the case.
    selected_by_paid_at DATETIME(6) NOT NULL,
    pinned_at           DATETIME(6) NOT NULL,
    PRIMARY KEY (case_id),
    CONSTRAINT fk_manifest_case FOREIGN KEY (case_id) REFERENCES aftersale_case (case_id),
    CONSTRAINT chk_manifest_hash CHECK (manifest_hash REGEXP '^[a-f0-9]{64}$'),
    CONSTRAINT chk_manifest_epoch CHECK (safety_epoch >= 0),
    CONSTRAINT chk_manifest_window CHECK (effective_to IS NULL OR effective_to > effective_from)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

CREATE TABLE case_policy_bundle (
    case_id   CHAR(36)    NOT NULL,
    bundle_id VARCHAR(64) NOT NULL,
    PRIMARY KEY (case_id, bundle_id),
    CONSTRAINT fk_case_bundle_manifest FOREIGN KEY (case_id) REFERENCES case_policy_manifest (case_id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;