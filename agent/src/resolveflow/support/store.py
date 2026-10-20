"""Small fenced consultation journal; completed calls replay, unknown in-flight calls never reset spend."""

import hashlib
from dataclasses import asdict

from psycopg.types.json import Jsonb

from resolveflow.harness.budget import RunSpend
from resolveflow.harness.context import canonical_json
from resolveflow.support.protocol import SupportFailure


class SupportStore:
    def __init__(self, database):
        self.database = database

    def claim(self, request, manifest):
        payload = request.model_dump(mode="json")
        with self.database.connection() as c, c.transaction():
            c.execute(
                """INSERT INTO support_agent_run(run_id,input_json,manifest_json,status,deadline_at,lease_until)
                         VALUES(%s,%s,%s,'RUNNING',%s,now()) ON CONFLICT DO NOTHING""",
                (request.run_id, Jsonb(payload), Jsonb(manifest), request.deadline_at),
            )
            row = c.execute(
                "SELECT *,lease_until>now() AS busy FROM support_agent_run WHERE run_id=%s FOR UPDATE",
                (request.run_id,),
            ).fetchone()
            if row["input_json"] != payload:
                raise SupportFailure("INPUT_MISMATCH")
            if row["result_json"] is not None:
                return None, row["result_json"]
            if row["manifest_json"] != manifest:
                raise SupportFailure("MANIFEST_MISMATCH")
            if row["busy"]:
                raise SupportFailure("RUN_BUSY")
            row = c.execute(
                """UPDATE support_agent_run SET fence=fence+1,lease_until=now()+interval '180 seconds'
                               WHERE run_id=%s RETURNING fence""",
                (request.run_id,),
            ).fetchone()
            return SupportJournal(self.database, request.run_id, row["fence"]), None


class SupportJournal:
    def __init__(self, database, run_id, fence):
        self.database, self.run_id, self.fence = database, run_id, fence

    def _lock(self, c):
        row = c.execute(
            """SELECT * FROM support_agent_run WHERE run_id=%s AND fence=%s
                           AND status='RUNNING' AND lease_until>now() FOR UPDATE""",
            (self.run_id, self.fence),
        ).fetchone()
        if row is None:
            raise SupportFailure("STALE_FENCE")
        return row

    def spend(self):
        with self.database.connection() as c, c.transaction():
            return asdict(RunSpend()) | self._lock(c)["spend_json"]

    def cached(self, kind, position, request):
        digest = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        with self.database.connection() as c, c.transaction():
            self._lock(c)
            row = c.execute(
                "SELECT * FROM support_agent_call WHERE run_id=%s AND kind=%s AND position=%s",
                (self.run_id, kind, position),
            ).fetchone()
            if row is None:
                return None
            if row["request_hash"] != digest:
                raise SupportFailure("CALL_MISMATCH")
            if row["status"] != "COMPLETE":
                raise SupportFailure("UNKNOWN_MODEL_RESULT" if kind == "model" else "INTERRUPTED_TOOL_RESULT")
            return row["response_json"]

    def start(self, kind, position, request, spend):
        digest = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        with self.database.connection() as c, c.transaction():
            self._lock(c)
            c.execute(
                """INSERT INTO support_agent_call(run_id,kind,position,request_hash,request_json,status)
                         VALUES(%s,%s,%s,%s,%s,'STARTED')""",
                (self.run_id, kind, position, digest, Jsonb(request)),
            )
            c.execute("UPDATE support_agent_run SET spend_json=%s WHERE run_id=%s", (Jsonb(spend), self.run_id))

    def complete(self, kind, position, response, spend):
        with self.database.connection() as c, c.transaction():
            self._lock(c)
            updated = c.execute(
                """UPDATE support_agent_call SET status='COMPLETE',response_json=%s
                                   WHERE run_id=%s AND kind=%s AND position=%s AND status='STARTED' """,
                (Jsonb(response), self.run_id, kind, position),
            )
            if updated.rowcount != 1:
                raise SupportFailure("CALL_STATE_MISMATCH")
            c.execute("UPDATE support_agent_run SET spend_json=%s WHERE run_id=%s", (Jsonb(spend), self.run_id))

    def generations(self):
        with self.database.connection() as c, c.transaction():
            return self._lock(c)["generations_json"]

    def pin_generations(self, generations):
        with self.database.connection() as c, c.transaction():
            row = self._lock(c)
            if row["generations_json"] is not None and row["generations_json"] != generations:
                raise SupportFailure("GENERATION_MISMATCH")
            c.execute(
                "UPDATE support_agent_run SET generations_json=%s WHERE run_id=%s", (Jsonb(generations), self.run_id)
            )

    def finish(self, result):
        with self.database.connection() as c, c.transaction():
            self._lock(c)
            c.execute(
                "UPDATE support_agent_run SET status=%s,result_json=%s WHERE run_id=%s",
                (result["status"], Jsonb(result), self.run_id),
            )
