"""Append-only ``agent_db`` migrations (C06.1).

SQL only: the runner is :func:`resolveflow.runtime.db.apply_migrations`, and these files are read as
package resources so a wheel and a source checkout apply the same schema.
"""