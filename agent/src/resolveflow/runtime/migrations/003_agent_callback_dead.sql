-- C06.1b — a delivery that can never succeed stops being queued work.
--
-- 002 gave the outbox two states: PENDING and DELIVERED. Delivering (1b-2) showed that is not enough. A
-- case service that answers 401, 403, 404, 409 or 422 is not having a bad minute: the service token is
-- wrong, the case is unknown, or the payload is one the contract refuses. Retrying those forever would
-- keep a healthy-looking queue that never drains, and it would hide an Agent bug (a payload the contract
-- rejects) behind what looks like a flaky network.
--
-- So a third state is appended: DEAD. The row is kept, not deleted — the callback was a decision the run
-- really reached, and the recorded reason is the only thing that explains why the case never learned it
-- (docs/domain-model.md:69). It is simply no longer retried.
--
-- Append-only: 002 has already run against a database, so this is a new file.

-- The status CHECK in 002 was written inline, so PostgreSQL named it. Dropped by discovering the name
-- rather than guessing it, which also makes this file safe on a database where 002 never ran.
DO $$
DECLARE
    existing_constraint text;
BEGIN
    IF to_regclass('agent_callback_outbox') IS NULL THEN
        RETURN;
    END IF;
    FOR existing_constraint IN
        SELECT con.conname
        FROM pg_constraint AS con
        JOIN pg_class AS rel ON rel.oid = con.conrelid
        JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
        WHERE rel.relname = 'agent_callback_outbox'
          AND ns.nspname = current_schema()
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%status%'
    LOOP
        EXECUTE format('ALTER TABLE agent_callback_outbox DROP CONSTRAINT %I', existing_constraint);
    END LOOP;
END $$;

DO $$
BEGIN
    IF to_regclass('agent_callback_outbox') IS NULL THEN
        RETURN;
    END IF;
    ALTER TABLE agent_callback_outbox
        ADD CONSTRAINT agent_callback_outbox_status_check
        CHECK (status IN ('PENDING', 'DELIVERED', 'DEAD'));
END $$;

-- And the retry counter: every attempt is counted, including the ones that end in DEAD, because "how many
-- times did we try before giving up" is part of the explanation.
COMMENT ON COLUMN agent_callback_outbox.last_error IS
    'Why the last attempt failed. Kept on DEAD rows, where it is the only explanation of a missing case update.';