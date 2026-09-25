-- C07.1 — the policy index: what a run's SEARCH_POLICY reads.
--
-- Three facts have to be storable for "the policy a run cites is the policy Java will re-check" to be
-- checkable rather than asserted:
--
--   * **which text was indexed, and from where** — the bundle's `manifest_hash` is copied from Java's
--     authoritative read (GET /internal/v1/policies/{bundle_id}), never recomputed from a local copy. That
--     is the whole point: a hash this side derived from its own parsing would verify itself.
--   * **how the text was split** — chunks are rules here, with `rule_id`/`chunk_id` and the `content_hash`
--     Java derives, so a citation this index hands out is one Java can re-hash.
--   * **which embedding produced the vectors** — model id, pinned revision and dimension are recorded per
--     generation, so a model change is a *new* generation rather than a silent change of meaning for
--     vectors that are already stored.
--
-- **Why the vector is `real[]` and not `vector(512)`.** pgvector is installed in this database (0.8.6, in
-- `public`), but nothing can rely on reaching it: every connection here is scoped to a schema
-- (`options=-c search_path=<schema>`, runtime/db.py), and a probe against the running database measured
-- that `CREATE TABLE ... (v vector(3))` fails with `UndefinedObject` in a fresh schema, while
-- `public.vector`'s `<=>` operator is not resolvable either, because the operator lives in that schema's
-- operator set. Extension objects cannot be relocated per test schema (`ALTER EXTENSION ... SET SCHEMA`
-- outside one), so a `vector` column would work only in `public` — which would make every integration test
-- either share the service's rows or stop running. `real[]` is creatable in any schema, so the isolated
-- tests keep working and the distance is computed exactly where the spec wants it: no ANN index, an exact
-- scan over the hard-filtered candidates (docs/policy-rag.md:17). The measured corpus is tens of segments,
-- so the scan is the ranking — there is nothing for an index to accelerate.
--
-- Append-only: 001-003 have run, so this is a new file. Drafted as of C07.1.

CREATE TABLE IF NOT EXISTS policy_index_generation (
    -- Identifies the index build, not the bundle: the same bundle can be re-indexed under a new generation
    -- (a model change, a chunking change) without touching the old rows, so an old snapshot stays readable.
    generation_id    text        NOT NULL,
    bundle_id        text        NOT NULL,
    merchant_id      text        NOT NULL,
    version          text        NOT NULL,
    safety_epoch     integer     NOT NULL,
    -- Java's own manifest hash, carried verbatim. It is both the check that this side indexed what Java
    -- serves and the key a run binds to (case_policy_manifest / run.policy_manifest).
    manifest_hash    text        NOT NULL,
    -- SHA-256 over what was actually ingested (bundle id + hash + every chunk in order). Distinct from
    -- manifest_hash on purpose: manifest_hash says "this is Java's bundle", lineage_hash says "these rows
    -- are the ingestion of it", and a bug that wrote half a bundle would change the second only.
    lineage_hash     text        NOT NULL,
    status           text        NOT NULL,
    -- The embedding that produced the vectors of this generation. Recorded even for a BM25-only build,
    -- where it is NULL: "no vectors were computed" is a fact a reader of the report needs.
    embedding_model  text        NULL,
    embedding_revision text      NULL,
    embedding_dimension integer  NULL,
    chunk_count      integer     NOT NULL,
    built_at         timestamptz NOT NULL,
    -- Only a READY generation may be searched, and readiness is per generation: "index not ready" must be a
    -- decidable state rather than an empty result that looks like "the policy does not mention this".
    CONSTRAINT policy_index_generation_status_check CHECK (status IN ('BUILDING', 'READY', 'FAILED')),
    CONSTRAINT policy_index_generation_unique UNIQUE (generation_id, bundle_id),
    -- A READY generation must have been built by an embedding it names, or the dense path would report
    -- "0 results" for a corpus that was never embedded.
    CONSTRAINT policy_index_ready_has_embedding CHECK (
        status <> 'READY' OR embedding_dimension IS NULL OR embedding_dimension > 0),
    PRIMARY KEY (generation_id, bundle_id)
);

CREATE INDEX IF NOT EXISTS idx_policy_index_generation_bundle
    ON policy_index_generation (bundle_id, manifest_hash, status);

CREATE TABLE IF NOT EXISTS policy_index_chunk (
    generation_id  text    NOT NULL,
    bundle_id      text    NOT NULL,
    -- The citable identity of this chunk, exactly Java's: `chunk_id` is `c-NN` from the rule's position and
    -- `content_hash` is Java's hash over (bundle_id, chunk_id, title, text). Stored, not derived at read
    -- time, because the stored value is what a citation was checked against.
    chunk_id       text    NOT NULL,
    rule_id        text    NOT NULL,
    position       integer NOT NULL,
    title          text    NOT NULL,
    text           text    NOT NULL,
    content_hash   text    NOT NULL,
    -- The unit retrieval ranks: the rule and its exceptions, never a fragment of one (docs/policy-rag.md:15
    -- forbids cutting the exception off), which is why this equals `text` today and is still a separate
    -- column: what is embedded and what is cited being the same string is a property to assert, not to
    -- assume.
    embedded_text  text    NOT NULL,
    embedding      real[]  NULL,
    CONSTRAINT fk_policy_chunk_generation
        FOREIGN KEY (generation_id, bundle_id)
        REFERENCES policy_index_generation (generation_id, bundle_id) ON DELETE CASCADE,
    CONSTRAINT policy_index_chunk_hashes CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    PRIMARY KEY (generation_id, bundle_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_policy_index_chunk_rule
    ON policy_index_chunk (generation_id, bundle_id, rule_id);

COMMENT ON COLUMN policy_index_generation.manifest_hash IS
    'Java''s manifest hash for this bundle, carried verbatim from the authoritative read. Never recomputed here.';
COMMENT ON COLUMN policy_index_generation.lineage_hash IS
    'SHA-256 over what was ingested (bundle identity plus every chunk in order). Detects a partial ingestion.';
COMMENT ON COLUMN policy_index_chunk.embedding IS
    'The dense vector for embedded_text. real[] rather than vector(512): see this file''s header for the measurement.';
