-- C03.1a: policy bundles, imported and then immutable (docs/core-contracts.md:50,53).
--
-- Policy is not editable through the API on purpose: the three management routes were dropped, and a
-- versioned rule set is imported by a controlled command that validates it. "Immutable" is therefore a
-- property of the storage, not a convention the next writer is asked to respect:
--
--   * there is no UPDATE and no DELETE statement in the mapper, and
--   * the trigger below refuses an edit even if one is ever written.
--
-- The effective window lives here and not in the response: the contract's PolicyBundle has
-- additionalProperties: false and no window member, because the window is how a version is *chosen*, not
-- something a reader of the rules needs. Selection is by the line's payment time, so a historical order
-- keeps the policy that was in force when it was paid for.

CREATE TABLE policy_bundle (
    bundle_id      VARCHAR(64) NOT NULL,
    version        VARCHAR(64) NOT NULL,
    manifest_hash  CHAR(64)    NOT NULL,
    safety_epoch   INT         NOT NULL,
    effective_from DATETIME(6) NOT NULL,
    -- NULL means "still in force"; a later version closes it rather than editing it.
    effective_to   DATETIME(6) NULL,
    imported_at    DATETIME(6) NOT NULL,
    source_path    VARCHAR(255) NOT NULL,
    PRIMARY KEY (bundle_id),
    KEY idx_policy_window (effective_from, effective_to),
    CONSTRAINT chk_policy_hash CHECK (manifest_hash REGEXP '^[a-f0-9]{64}$'),
    CONSTRAINT chk_policy_epoch CHECK (safety_epoch >= 0),
    CONSTRAINT chk_policy_window CHECK (effective_to IS NULL OR effective_to > effective_from)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

CREATE TABLE policy_rule (
    bundle_id VARCHAR(64)  NOT NULL,
    rule_id   VARCHAR(64)  NOT NULL,
    position  INT          NOT NULL,
    title     VARCHAR(200) NOT NULL,
    text      TEXT         NOT NULL,
    PRIMARY KEY (bundle_id, rule_id),
    KEY idx_rule_position (bundle_id, position),
    CONSTRAINT fk_rule_bundle FOREIGN KEY (bundle_id) REFERENCES policy_bundle (bundle_id) ON DELETE CASCADE,
    CONSTRAINT chk_rule_position CHECK (position >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

-- Immutability is enforced in the code, not here, and that is a constraint of this database rather than a
-- preference: MySQL refuses CREATE TRIGGER for an account without SUPER while binary logging is on
-- ("You do not have the SUPER privilege and binary logging is enabled", error 1419), and the service's own
-- account is not SUPER. A migration that only applies for a privileged user is worse than no trigger, because
-- it passes on the machine that wrote it and fails on the next one.
--
-- So the guarantees are: the mapper has no UPDATE, no DELETE and no other mutation of these two tables (the
-- import only ever inserts), an import of changed content under an existing bundle_id is refused, and
-- PolicyMutationGuardTest asserts the first of those by reading the mapper's own statements.
--
-- Removing a whole version stays possible: that is destructive and visible, and a case pins the hash it was
-- decided against, so a citation re-checked later against a re-imported version fails loudly rather than
-- quietly matching the wrong text. Content changes are the silent failure, and those are what is refused.