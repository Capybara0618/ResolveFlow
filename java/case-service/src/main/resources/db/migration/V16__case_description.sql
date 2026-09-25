-- C06.1c — the case keeps the customer's own words.
--
-- The description was only inside the CASE_CREATED timeline detail, which is where a reader sees it. The
-- run request needs it too: the Agent's contract requires `request.description` — the model is asked about
-- the customer's problem, and a dispatch that left it blank would start an investigation of nothing
-- (contracts/core/openapi-agent.yaml:78-81). Reading it back out of the timeline's JSON detail would make
-- a presentation format into a stored contract, and it would leave the dispatch unable to run if that
-- format ever changed shape. It is a fact about the case, so it gets a column.
--
-- Backfilled for rows that already exist: a database upgraded from before this migration has cases whose
-- description is still only in the timeline, and an empty string would be a lie about a case that has one.
--
-- Migrations are append-only (docs/engineering.md:64): this file is never edited after it has run.

-- The customer's own words, as submitted. Copied into every run dispatch, which is why it is a column
-- rather than something read back out of the timeline's JSON detail.
ALTER TABLE aftersale_case
    ADD COLUMN description TEXT NULL
    COMMENT 'The customer''s own words, as submitted (contracts/core/openapi-agent.yaml:78).';

UPDATE aftersale_case c
SET c.description = (
    SELECT JSON_UNQUOTE(JSON_EXTRACT(t.detail, '$.description'))
    FROM case_timeline t
    WHERE t.case_id = c.case_id AND t.kind = 'CASE_CREATED'
    ORDER BY t.sequence
    LIMIT 1
)
WHERE c.description IS NULL;

-- New rows always carry one (CaseWriter writes it with the case), so the column is only nullable for the
-- window this migration runs in. It is not tightened to NOT NULL here: a database upgraded from before this
-- migration whose timeline detail had no description to backfill from would fail the migration itself, and
-- a migration that cannot run is worse than a column that could be stricter. New writes always set it.