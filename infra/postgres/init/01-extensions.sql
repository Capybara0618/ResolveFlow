-- Agent database bootstrap (docs/architecture.md: the Agent uses PostgreSQL for
-- LangGraph checkpoints, policy index and vector search, and it is the only
-- owner of agent_db).
--
-- The agent_db database itself is created by the image via POSTGRES_DB.

-- pgvector for the policy index (T19). Exact search is used by default on the
-- small corpus; the extension is installed now so the T19 migration does not
-- depend on a superuser step at runtime.
CREATE EXTENSION IF NOT EXISTS vector;