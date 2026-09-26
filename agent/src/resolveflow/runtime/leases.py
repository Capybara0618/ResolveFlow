"""PG lease plus session advisory lock. The lock connection is retained, never a network-spanning transaction."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from resolveflow.contracts.enums import CallbackKind
from resolveflow.harness.vocabulary import RunFacts
from resolveflow.runtime.callbacks import CallbackEnvelope, CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.worker import ClaimedRun, _active_deadline, started_payload


@dataclass
class RunLease:
    database: Database
    owner: str = ""
    seconds: float = 30

    def __post_init__(self) -> None:
        self.owner = self.owner or f"worker-{uuid.uuid4()}"

    def renew(self, run_id: str, fence: int) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                "UPDATE agent_run SET lease_until=clock_timestamp()+(%s*interval '1 second') "
                "WHERE run_id=%s AND fence=%s AND lease_owner=%s AND status='RUNNING' "
                "AND cancelled_at IS NULL AND lease_until>clock_timestamp() RETURNING run_id",
                (self.seconds, run_id, fence, self.owner),
            ).fetchone()
            return row is not None

    @contextmanager
    def acquire(self) -> Iterator[ClaimedRun | None]:
        lock_key = None
        stopped = threading.Event()
        heartbeat = None
        with self.database.connection() as connection:
            try:
                with connection.transaction():
                    row = connection.execute(
                        "SELECT * FROM agent_run WHERE cancelled_at IS NULL AND "
                        "(status='QUEUED' OR (status='RUNNING' AND lease_until<clock_timestamp())) "
                        "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
                    ).fetchone()
                    claimed = None
                    if row is not None:
                        candidate = f"{self.database.schema}:{row['run_id']}"
                        acquired = connection.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok",
                                                      (candidate,)).fetchone()
                        if acquired is not None and acquired["ok"]:
                            lock_key = candidate
                            clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
                            assert clock is not None
                            now = clock["now"]
                            window = row["active_deadline_at"] or _active_deadline(row["deadline_at"], now)
                            fence = int(row["fence"] or 0) + 1
                            connection.execute(
                                "UPDATE agent_run SET status='RUNNING',fence=%s,lease_owner=%s,"
                                "lease_until=clock_timestamp()+(%s*interval '1 second'),active_deadline_at=%s,"
                                "version=version+1,updated_at=clock_timestamp() WHERE run_id=%s",
                                (fence, self.owner, self.seconds, window, row["run_id"]),
                            )
                            if row["status"] == "QUEUED":
                                CallbackStore(self.database).enqueue_for_run(
                                    str(row["run_id"]), CallbackEnvelope(kind=CallbackKind.STARTED,
                                    payload=started_payload(now), traceparent=row["traceparent"]),
                                    connection=connection,
                                )
                            claimed = ClaimedRun(
                                RunFacts(run_id=str(row["run_id"]), case_id=str(row["case_id"]),
                                         input_revision=row["input_revision"], line_id=row["line_id"],
                                         description=row["request_description"], merchant_id=row["merchant_id"],
                                         customer_id=row["customer_id"], active_deadline_at=window.isoformat(),
                                         policy_manifest=row["policy_manifest"], fence=fence, lease_owner=self.owner),
                                str(row["case_id"]), row["traceparent"],
                            )
                if claimed is not None:
                    facts = claimed.facts

                    def tick() -> None:
                        while not stopped.wait(self.seconds / 3):
                            if not self.renew(facts.run_id, int(facts.fence or 0)):
                                return

                    heartbeat = threading.Thread(target=tick, daemon=True, name="run-lease-heartbeat")
                    heartbeat.start()
                yield claimed
            finally:
                stopped.set()
                if heartbeat is not None:
                    heartbeat.join(timeout=self.seconds)
                if lock_key is not None:
                    connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock_key,))
