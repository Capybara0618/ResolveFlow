-- C07.1: the merchant a policy bundle belongs to, and the merchant a pinned manifest was selected for.
--
-- Why the column exists at all, given a case row already has merchant_id: the pinned manifest is the record a
-- run is *dispatched with*, and C07.1's retrieval has to hard-filter by merchant before it ranks anything
-- (docs/policy-rag.md:15). A run that could only learn its merchant from the case row would make "filter by
-- the run's merchant" depend on a second read the manifest route does not have.
--
-- Why not derive it from policy_bundle at read time: a manifest is a pin, and the point of a pin is that what
-- it says stays true even if the policy table moves on. Re-deriving the merchant would be the same mistake as
-- re-deriving the safety epoch, which V5 already refuses to do.
--
-- ---------------------------------------------------------------------------------------------------------
-- Both columns are added NULL and then back-filled; only the manifest's becomes NOT NULL. The order matters and
-- it is not a formality: these tables already hold rows on any database that is not fresh (imported versions,
-- and the cases pinned to them), and MySQL has no single-step way to add a NOT NULL column with no default. The
-- alternative — add it with DEFAULT '' and let the sentinel stand for "unknown merchant" — was rejected
-- deliberately, and the section below says what replaced it and why.
--
-- The back-fill is a real statement rather than a placeholder, because the answer is already in the database:
-- a case row has always carried the merchant whose payment selected its policy, and a case's pinned bundles are
-- the policy set of that merchant. So the provenance runs case_policy_bundle → aftersale_case, and one merchant
-- is not an assumption this migration has to make.
--
-- The aggregate is not decoration, and its absence is a bug this migration shipped with for three test runs. A
-- bundle cited by cases of two different merchants — which is exactly the state a pre-C07.1 database can be in,
-- because selection used to ignore the merchant — gives a correlated subquery two rows and MySQL answers
-- "Subquery returns more than 1 row" (error 1242). That happened on this machine's own compose database, which
-- held three M-1002 cases pinned to M-1001's logistics bundle: data the new code makes impossible, left over
-- from the behaviour it replaces.
--
-- So the back-fill is written as a **derived table joined once**, which is total by construction: the GROUP BY
-- guarantees at most one row per bundle, so no stored state can make the migration fail. MIN() picks
-- deterministically among the merchants that claimed a bundle; the inconsistency itself is caught where it can
-- be acted on — C07.1's retrieval refuses a run whose merchant does not match its pinned bundle's merchant, and
-- PolicySelectionService refuses to select across merchants. A migration that cannot be repaired from inside
-- itself should still leave the schema usable: a service that will not start is not a safer outcome than one
-- that starts and refuses the bad case loudly.
--
-- **A bundle no case ever pinned cannot be attributed, and that is a real state, not an edge case**: an import
-- installs versions that nothing has selected yet, and a fresh database has the whole imported set that way.
-- The correlation above found no merchant for one of the two shipped fixtures on this very machine, and the
-- first version of this migration then failed its own NOT NULL.
--
-- So ``policy_bundle.merchant_id`` is **nullable, and a NULL means "nobody has told this bundle whose policy set
-- it is"**. The alternatives were each worse:
--
--   * a sentinel (``''`` or ``'UNATTRIBUTED'``) — rejected as this file originally said, because every filter
--     compares a merchant against it and a sentinel makes the filter quietly absent. Making it unwritable with a
--     CHECK only moved the failure: the back-fill itself then violated the constraint on exactly that row;
--   * a NOT NULL with an invented merchant — attributing a policy set to someone who may never have written it,
--     which is the one thing this column exists to prevent;
--   * refusing the migration — a service that will not start because a fixture was imported before any case
--     selected it, with no way for the operator to fix it from inside the migration.
--
-- What makes the NULL safe is that nothing reaches a run through it. A run's policy comes from a **case pin**
-- (``case_policy_manifest.merchant_id``, below, which is NOT NULL because every case row has a merchant), and
-- the Agent side refuses a served bundle whose merchant is missing (``served_bundle_of``). The bundle route is
-- the only place this column is published, and it is read by the ingestion script, which fails on a bundle it
-- cannot attribute rather than indexing an ownerless policy set.
-- ---------------------------------------------------------------------------------------------------------

ALTER TABLE policy_bundle
    ADD COLUMN merchant_id VARCHAR(64) NULL AFTER bundle_id;

UPDATE policy_bundle p
    JOIN (
        SELECT b.bundle_id AS bundle_id, MIN(c.merchant_id) AS merchant_id
          FROM case_policy_bundle b
          JOIN aftersale_case c ON c.case_id = b.case_id
         GROUP BY b.bundle_id
    ) AS claimed ON claimed.bundle_id = p.bundle_id
   SET p.merchant_id = claimed.merchant_id
 WHERE p.merchant_id IS NULL;

-- A bundle nothing pinned is attributed from the **policy set already installed for this merchant**, when there
-- is exactly one such merchant. That is the case on a fresh or single-merchant database, where the imported set
-- is unambiguously one merchant's and leaving it NULL would only postpone the problem to the next import (the
-- ambiguity check in PolicyWriter compares windows per merchant, and an ownerless window is skipped rather than
-- matched — see the null guard there).
--
-- The COUNT guard is what keeps this from being a guess: with two merchants installed and no case to attribute
-- a bundle from, the statement does nothing and the row stays NULL, which is the honest answer. No shipped
-- database is in that state, and inventing an owner is the one thing this column exists to prevent.
UPDATE policy_bundle
   SET merchant_id = (
        SELECT * FROM (
            SELECT MIN(installed.merchant_id)
              FROM policy_bundle AS installed
             WHERE installed.merchant_id IS NOT NULL) AS only_merchant)
 WHERE merchant_id IS NULL
   -- MySQL refuses a statement that reads the table it updates (error 1093), and the fix is the derived table:
   -- a subquery in the FROM clause is materialised, so this is a read of a snapshot rather than of the rows being
   -- written. The COUNT is the same guard as the aggregate: with two merchants installed and no case to attribute
   -- a bundle from, the statement does nothing and the row stays NULL, which is the honest answer.
   AND (SELECT count_of FROM (
            SELECT COUNT(DISTINCT installed.merchant_id) AS count_of
              FROM policy_bundle AS installed
             WHERE installed.merchant_id IS NOT NULL) AS installed_merchants) = 1;

CREATE INDEX idx_policy_bundle_merchant ON policy_bundle (merchant_id, effective_from);

-- The pinned manifest records the merchant its window was chosen for, for the same reason it records the
-- window: "why this policy" has to be answerable from the case itself, and after C07.1 "whose policy" is
-- part of that answer.
ALTER TABLE case_policy_manifest
    ADD COLUMN merchant_id VARCHAR(64) NULL AFTER case_id;

UPDATE case_policy_manifest m
    JOIN aftersale_case c ON c.case_id = m.case_id
   SET m.merchant_id = c.merchant_id
 WHERE m.merchant_id IS NULL;

ALTER TABLE case_policy_manifest
    MODIFY COLUMN merchant_id VARCHAR(64) NOT NULL;
