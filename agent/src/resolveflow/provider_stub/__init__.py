"""The refund provider's protocol, as the stub implements it (C04.1).

The provider is not a business service: it is the outside world that can take money, refuse to take
it, or leave the caller without an answer (docs/architecture.md:13, docs/core-scope.md:30). What
Commerce needs from it is small enough to state exactly:

``request_refund(operation_id, line_id, amount_minor, currency)``
    Asks for one refund. ``operation_id`` **is** the provider's idempotency key
    (docs/domain-model.md:51): upstream retries with the same operation, so the provider must answer
    a repeat with the first answer rather than paying again.

``query_refund(operation_id_or_provider_ref)``
    Reads what the provider currently believes. It is how an UNKNOWN is eventually resolved.

Two distinctions carry most of the design:

- **Unknown is not failed.** ``UNKNOWN`` means no answer arrived; upstream must keep the money
  reserved (docs/domain-model.md:15). ``FAILED`` is a determined refusal, and it is terminal: the
  key is never resurrected, because upstream has already released the reservation by then.
- **Not found is not failed either.** A provider that cannot see its own completed payment yet is
  still going to have taken the money. ``NOT_FOUND`` therefore says "I have nothing", which is what
  a delayed-visibility provider answers inside its visibility window.

The stub records the outcome even when the caller never hears it: a lost response has to leave the
provider settled, or "retry after a timeout" could not be told apart from "pay twice".
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

UNKNOWN = "UNKNOWN"

SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
NOT_FOUND = "NOT_FOUND"

#: Fault names a caller may inject, and what each one means for the caller's answer.
#:
#: - ``REQUEST_TIMEOUT``     nothing is settled; the operation is recorded UNKNOWN.
#: - ``LOST_RESPONSE``       the outcome is settled and recorded, but the reply never arrives.
#: - ``DELAYED_VISIBILITY``  the outcome is settled, but a query cannot see it until ``visible_after``.
#: - ``DECLINE``             a determined refusal, terminal for that key.
FAULTS = ("REQUEST_TIMEOUT", "LOST_RESPONSE", "DELAYED_VISIBILITY", "DECLINE")


class ProviderConflictError(RuntimeError):
    """The key is already in use for a different payment.

    The stub refuses rather than overwriting: an overwrite would make "what was paid" depend on the
    last writer, which is exactly the failure the operation's own uniqueness exists to prevent
    (docs/domain-model.md:11).
    """

    def __init__(self, operation_id: str, reason: str) -> None:
        super().__init__(f"{operation_id}: {reason}")
        self.operation_id = operation_id
        self.reason = reason


@dataclass(frozen=True)
class RefundResult:
    """What the provider believes about one refund, as read at one moment.

    ``responded`` is separate from ``state`` on purpose. A lost response and a timeout both leave the
    caller without an answer, but only the first has an outcome the provider already knows: confusing
    the two is how a retry turns into a second payment.
    """

    operation_id: str
    state: str
    provider_ref: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    reason_code: str | None = None
    settled_at: dt.datetime | None = None
    visible_after: dt.datetime | None = None
    responded: bool = True
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in {SUCCEEDED, FAILED}


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Store every instant in UTC, so a restart cannot change what "already visible" means."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class RefundProviderStub:
    """A persistent simulated refund channel (C04.1).

    Everything lives in one SQLite file: the requests, the attempts, and the injected faults. There is
    deliberately no in-process cache, because a stub whose state survived only in memory could not be
    used to test the thing it exists for — a provider that outlives the caller
    (docs/core-scope.md:30).
    """

    def __init__(self, path: str | Path, *, clock: Callable[[], dt.datetime] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        # Rows are read by column name, so a column added by a later migration cannot silently shift
        # every reader by one position.
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> RefundProviderStub:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS refund_request (
                operation_id  TEXT PRIMARY KEY,
                line_id       TEXT NOT NULL,
                amount_minor  INTEGER NOT NULL CHECK (amount_minor > 0),
                currency      TEXT NOT NULL,
                state         TEXT NOT NULL,
                provider_ref  TEXT,
                reason_code   TEXT,
                requested_at  TEXT NOT NULL,
                settled_at    TEXT,
                visible_after TEXT
            );

            CREATE TABLE IF NOT EXISTS request_attempt (
                operation_id TEXT NOT NULL,
                attempt      INTEGER NOT NULL,
                at           TEXT NOT NULL,
                outcome      TEXT NOT NULL,
                PRIMARY KEY (operation_id, attempt)
            );

            CREATE TABLE IF NOT EXISTS injected_fault (
                operation_id  TEXT,
                fault         TEXT NOT NULL,
                reason_code   TEXT,
                visible_after TEXT,
                PRIMARY KEY (operation_id, fault)
            );
            """
        )

    # ------------------------------------------------------------------ fault injection

    def inject(
        self,
        fault: str,
        *,
        operation_id: str | None = None,
        reason_code: str | None = None,
        visible_after: dt.datetime | None = None,
    ) -> None:
        """Arm one fault, for one operation or for every operation when the id is omitted."""
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}; known faults are {', '.join(FAULTS)}")
        self._connection.execute(
            "INSERT OR REPLACE INTO injected_fault (operation_id, fault, reason_code, visible_after)"
            " VALUES (?, ?, ?, ?)",
            (
                operation_id,
                fault,
                reason_code,
                _as_utc(visible_after).isoformat() if visible_after else None,
            ),
        )

    def clear_faults(self) -> None:
        self._connection.execute("DELETE FROM injected_fault")

    def _fault_for(self, operation_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT fault, reason_code, visible_after FROM injected_fault"
            " WHERE operation_id IS ? OR operation_id = ?"
            " ORDER BY operation_id IS NULL LIMIT 1",
            (operation_id, operation_id),
        ).fetchone()

    # ------------------------------------------------------------------ the protocol

    def request_refund(
        self,
        *,
        operation_id: str,
        line_id: str,
        amount_minor: int,
        currency: str,
        requested_at: dt.datetime | None = None,
    ) -> RefundResult:
        """Ask for one refund, idempotently by ``operation_id``."""
        if not operation_id:
            raise ValueError("operation_id is required: it is the provider's idempotency key")
        if amount_minor <= 0:
            raise ValueError(f"amount_minor must be positive, not {amount_minor}")
        if not currency:
            raise ValueError("currency is required")

        at = _as_utc(requested_at or self._clock())
        previous = self._find(operation_id)

        if previous is not None:
            # A repeat is not a new attempt. The provider already has a receipt for this key, so the
            # honest description of what it did is "returned the receipt" — counting it as a payment
            # attempt would make the stub claim it asked the outside world twice when it did not.
            #
            # A settled outcome is returned whatever the original fault was. The lost-response fault
            # means the *first* reply never arrived; it does not mean every later answer is lost too, or
            # the retry that exists to recover the outcome could never recover it.
            stored = self._same_payload(previous, line_id, amount_minor, currency)
            self._record_attempt(operation_id, "REPEAT", at)
            # A repeat always gets a real reply: the provider answers from the receipt it holds. Only an
            # UNKNOWN key has nothing to hand back, because there is no outcome to report yet.
            return self._answered(stored, responded=stored["state"] != UNKNOWN)

        # A key with no row has never been requested. From here on the key is reserved.
        fault = self._fault_for(operation_id)
        name = fault["fault"] if fault else None
        outcome = self._outcome_for(name, amount_minor, at, fault)

        self._connection.execute(
            "INSERT INTO refund_request (operation_id, line_id, amount_minor, currency, state, provider_ref,"
            " reason_code, requested_at, settled_at, visible_after) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                operation_id,
                line_id,
                amount_minor,
                currency,
                outcome["state"],
                outcome["provider_ref"],
                outcome["reason_code"],
                at.isoformat(),
                outcome["settled_at"],
                outcome["visible_after"],
            ),
        )
        self._record_attempt(operation_id, name or "SETTLED", at)
        written = self._find(operation_id)
        assert written is not None, "the row was just written"
        # A timeout has no outcome to report; a lost response has one the caller did not receive. Both
        # tell the caller "I have nothing for you", which is what UNKNOWN means upstream
        # (docs/domain-model.md:15) — the stored state is where the difference survives, and the repeat
        # call is what recovers it.
        return self._answered(written, responded=name != "LOST_RESPONSE" and written["state"] != UNKNOWN)

    def query_refund(self, key: str, *, at: dt.datetime | None = None) -> RefundResult:
        """Read the provider's belief, by operation or by the reference it handed out."""
        row = self._find_by_provider_ref(key) or self._find(key)
        if row is None:
            return RefundResult(operation_id=key, state=NOT_FOUND)
        if row["visible_after"] is not None:
            visible_after = dt.datetime.fromisoformat(row["visible_after"])
            if _as_utc(at or self._clock()) < visible_after:
                return RefundResult(
                    operation_id=row["operation_id"],
                    state=NOT_FOUND,
                    amount_minor=row["amount_minor"],
                    currency=row["currency"],
                    visible_after=visible_after,
                    detail={"reason": "this provider cannot see its own payment yet"},
                )
        return self._answered(row, responded=True)

    def settle(self, operation_id: str, *, state: str, reason_code: str | None = None) -> RefundResult:
        """Resolve an UNKNOWN by hand, which is what a provider's reconciliation window does."""
        if state not in {SUCCEEDED, FAILED}:
            raise ValueError(f"an operation settles to {SUCCEEDED} or {FAILED}, not {state}")
        row = self._find(operation_id)
        if row is None:
            raise KeyError(operation_id)
        if row["state"] != UNKNOWN:
            return self._answered(row, responded=True)
        at = _as_utc(self._clock())
        self._connection.execute(
            "UPDATE refund_request SET state = ?, reason_code = ?, settled_at = ?,"
            " provider_ref = COALESCE(provider_ref, ?) WHERE operation_id = ?",
            (state, reason_code, at.isoformat(), self._new_provider_ref(), operation_id),
        )
        updated = self._find(operation_id)
        assert updated is not None
        return self._answered(updated, responded=True)

    def attempts(self, operation_id: str) -> int:
        """How many times the provider was actually asked to move money for this key.

        Repeats are excluded: a repeat returns the receipt the provider already has, so counting it
        would make the stub report requests it never made. Refusals are excluded too — a conflicting
        key is rejected before the provider is called (see {@link ProviderConflictError}).
        """
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM request_attempt WHERE operation_id = ? AND outcome != 'REPEAT'",
            (operation_id,),
        ).fetchone()
        assert row is not None
        return int(row["n"])

    def receipts(self, operation_id: str) -> int:
        """How many times this key was presented, refusals and repeats included.

        This is the other half of {@link attempts}: a caller checking idempotency wants to know the
        provider was reached once while it was asked three times.
        """
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM request_attempt WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        assert row is not None
        return int(row["n"])

    # ------------------------------------------------------------------ internals

    def _outcome_for(
        self, fault: str | None, amount_minor: int, at: dt.datetime, injected: sqlite3.Row | None
    ) -> dict[str, str | None]:
        if fault == "REQUEST_TIMEOUT":
            return {"state": UNKNOWN, "provider_ref": None, "reason_code": "PROVIDER_TIMEOUT", "settled_at": None,
                    "visible_after": None}
        if fault == "DECLINE":
            return {
                "state": FAILED,
                "provider_ref": None,
                "reason_code": (injected["reason_code"] if injected else None) or "DECLINED",
                "settled_at": at.isoformat(),
                "visible_after": None,
            }
        visible_after = None
        if fault == "DELAYED_VISIBILITY" and injected is not None and injected["visible_after"]:
            visible_after = injected["visible_after"]
        return {
            "state": SUCCEEDED,
            "provider_ref": self._new_provider_ref(),
            "reason_code": None,
            "settled_at": at.isoformat(),
            "visible_after": visible_after,
        }

    def _same_payload(self, row: sqlite3.Row, line_id: str, amount_minor: int, currency: str) -> sqlite3.Row:
        if row["line_id"] != line_id:
            raise ProviderConflictError(row["operation_id"], f"key already used for line {row['line_id']}")
        if row["amount_minor"] != amount_minor:
            raise ProviderConflictError(
                row["operation_id"], f"key already used for amount {row['amount_minor']}, not {amount_minor}"
            )
        if row["currency"] != currency:
            raise ProviderConflictError(row["operation_id"], f"key already used for currency {row['currency']}")
        return row

    def _find(self, operation_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM refund_request WHERE operation_id = ?", (operation_id,)
        ).fetchone()

    def _find_by_provider_ref(self, provider_ref: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM refund_request WHERE provider_ref = ?", (provider_ref,)
        ).fetchone()

    def _record_attempt(self, operation_id: str, outcome: str, at: dt.datetime) -> None:
        self._connection.execute(
            "INSERT INTO request_attempt (operation_id, attempt, at, outcome) VALUES (?, ?, ?, ?)",
            (
                operation_id,
                self.attempts(operation_id) + 1,
                at.isoformat(),
                outcome,
            ),
        )

    @staticmethod
    def _new_provider_ref() -> str:
        return f"prv-{uuid.uuid4()}"

    def _answered(self, row: sqlite3.Row, *, responded: bool) -> RefundResult:
        return RefundResult(
            operation_id=row["operation_id"],
            state=row["state"],
            provider_ref=row["provider_ref"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            reason_code=row["reason_code"],
            settled_at=dt.datetime.fromisoformat(row["settled_at"]) if row["settled_at"] else None,
            visible_after=dt.datetime.fromisoformat(row["visible_after"]) if row["visible_after"] else None,
            responded=responded,
        )
