"""The provider stub must answer the one question the money path asks it, and answer it the same way twice.

These are the properties C04.1 owes (tasks/todo.md C04.1, docs/domain-model.md:11,15,51):

- the same key with the same payload returns the original result; the same key with a different
  payload is refused, because a provider that accepted it would make "what was paid" depend on the
  last writer;
- a query for a key that was never requested says NOT_FOUND, which is not a failure: the outcome of
  an UNKNOWN operation is unknown until the provider says otherwise, and "release the money" is
  never a correct reading of "no answer yet";
- a lost response leaves the outcome settled, so the retry returns the original result instead of
  paying twice;
- a timeout is not a failure: it is recorded as UNKNOWN and stays UNKNOWN until it settles;
- the whole thing survives the process, because a stub whose memory was its database could not be
  used to test a restart;
- and the property nobody may break: a key retired as FAILED is never resurrected by a later
  request, because upstream treats a released failure as "the money is free again".

The tests run against SQLite files in a temporary directory, so restart is a real reopen of the
same file rather than a mock of one.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from resolveflow.provider_stub import (
    FAILED,
    FAULTS,
    NOT_FOUND,
    SUCCEEDED,
    UNKNOWN,
    ProviderConflictError,
    RefundProviderStub,
)

#: The repository root, found from this file rather than from the working directory, so the test that
#: reads the protocol document works the same whether pytest was started in the repository or in agent/.
REPO_ROOT = Path(__file__).resolve().parents[3]

OPERATION = "0f0f0f0f-1111-4222-8333-444444444444"
LINE = "7001"
AMOUNT = 2599


def request(stub: RefundProviderStub, *, operation: str = OPERATION, amount: int = AMOUNT, line: str = LINE):
    return stub.request_refund(
        operation_id=operation,
        line_id=line,
        amount_minor=amount,
        currency="CNY",
        requested_at=dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC),
    )


def test_the_same_key_and_payload_returns_the_original_result(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")

    first = request(stub)
    second = request(stub)

    assert first.state == "SUCCEEDED"
    assert second == first, "a retry of the same payment has to be the same payment"
    assert stub.query_refund(OPERATION).provider_ref == first.provider_ref


def test_the_same_key_with_a_different_payload_is_refused(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    request(stub)

    with pytest.raises(ProviderConflictError):
        request(stub, amount=AMOUNT + 1)

    with pytest.raises(ProviderConflictError):
        request(stub, line="7002")


def test_a_repeat_is_not_a_second_attempt_at_the_provider(tmp_path: Path) -> None:
    """The key upstream retries with is the operation id, and a repeat must not look like a new payment."""
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")

    first = request(stub)
    with pytest.raises(ProviderConflictError):
        request(stub, amount=1)
    again = request(stub)

    assert again.provider_ref == first.provider_ref
    assert stub.attempts(OPERATION) == 1, "one request reached the provider; everything after it is a repeat"
    assert stub.receipts(OPERATION) == 2, "and the key was presented twice, which is what idempotency is for"


def test_an_unrequested_key_is_not_found_rather_than_failed(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")

    answer = stub.query_refund("ffffffff-0000-4000-8000-000000000000")

    assert answer.state == "NOT_FOUND"
    assert answer.provider_ref is None
    assert answer.amount_minor is None


def test_a_lost_response_is_recorded_and_the_retry_returns_the_original(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    stub.inject("LOST_RESPONSE", operation_id=OPERATION)

    lost = request(stub)

    assert lost.responded is False
    assert lost.state == "SUCCEEDED", "the provider did pay; the caller is simply the one who did not hear"
    assert stub.query_refund(OPERATION).state == "SUCCEEDED"
    assert stub.attempts(OPERATION) == 1, "a settled key is never requested a second time at the provider"

    retry = request(stub)

    assert retry.responded is True, "the retry is answered: the provider had the outcome all along"
    assert replace(retry, responded=False) == replace(
        lost, responded=False
    ), "and it is the original result, not a second payment"


def test_a_timeout_is_unknown_and_stays_unknown_until_it_settles(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    stub.inject("REQUEST_TIMEOUT", operation_id=OPERATION)

    answer = request(stub)

    assert answer.state == UNKNOWN
    assert answer.responded is False
    assert stub.query_refund(OPERATION).state == UNKNOWN, "no answer is not a failure and not a success"

    settled = stub.settle(OPERATION, state="SUCCEEDED")

    assert settled.state == "SUCCEEDED"
    assert stub.query_refund(OPERATION).state == "SUCCEEDED"


def test_an_injected_decline_is_a_terminal_failure(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    stub.inject("DECLINE", operation_id=OPERATION, reason_code="INSUFFICIENT_FUNDS")

    refused = request(stub)

    assert refused.state == "FAILED"
    assert refused.reason_code == "INSUFFICIENT_FUNDS"
    assert stub.query_refund(OPERATION).state == "FAILED"


def test_delayed_visibility_answers_not_found_until_the_window_passes(tmp_path: Path) -> None:
    """A provider that has taken the money but cannot see it yet must not be read as "nothing happened"."""
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    at = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC)
    stub.inject("DELAYED_VISIBILITY", operation_id=OPERATION, visible_after=at + dt.timedelta(seconds=30))

    answered = stub.request_refund(
        operation_id=OPERATION, line_id=LINE, amount_minor=AMOUNT, currency="CNY", requested_at=at
    )

    assert answered.state == "SUCCEEDED"
    assert stub.query_refund(OPERATION, at=at + dt.timedelta(seconds=10)).state == "NOT_FOUND"
    assert stub.query_refund(OPERATION, at=at + dt.timedelta(seconds=31)).state == "SUCCEEDED"


def test_a_failed_key_is_never_resurrected_by_a_later_request(tmp_path: Path) -> None:
    """Upstream releases the money on a determined failure, so a second success on that key would double-pay."""
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")
    stub.inject("DECLINE", operation_id=OPERATION)
    assert request(stub).state == "FAILED"

    stub.clear_faults()
    refused = request(stub)

    assert refused.state == "FAILED", "the tombstone is the answer, not a fresh attempt"
    assert stub.attempts(OPERATION) == 1, "and the failed key was never sent to the provider a second time"
    assert stub.receipts(OPERATION) == 2, "the second submission is answered from the record"
    assert stub.query_refund(OPERATION).state == "FAILED"


def test_the_outcome_survives_a_reopen_of_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "provider.sqlite3"
    first = RefundProviderStub(path)
    settled = request(first)
    first.inject("REQUEST_TIMEOUT", operation_id="1f1f1f1f-1111-4222-8333-444444444444")
    first.request_refund(
        operation_id="1f1f1f1f-1111-4222-8333-444444444444",
        line_id="7002",
        amount_minor=1999,
        currency="CNY",
        requested_at=dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC),
    )
    first.close()

    reopened = RefundProviderStub(path)

    assert reopened.query_refund(OPERATION) == settled
    unknown = reopened.query_refund("1f1f1f1f-1111-4222-8333-444444444444")
    assert unknown.state == UNKNOWN
    assert reopened.attempts(OPERATION) == 1, "the attempt counter is not reset by a restart"


def test_the_database_is_the_only_state(tmp_path: Path) -> None:
    """No in-process cache may answer for the store: a cache is what makes a restart test a lie."""
    path = tmp_path / "provider.sqlite3"
    stub = RefundProviderStub(path)
    request(stub)

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT state, amount_minor, provider_ref FROM refund_request").fetchall()
    finally:
        connection.close()

    assert rows == [("SUCCEEDED", AMOUNT, stub.query_refund(OPERATION).provider_ref)]


def test_a_zero_or_negative_amount_is_refused_before_the_provider_is_called(tmp_path: Path) -> None:
    stub = RefundProviderStub(tmp_path / "provider.sqlite3")

    for bad in (0, -1):
        with pytest.raises(ValueError):
            request(stub, amount=bad)

    assert stub.attempts(OPERATION) == 0


def test_the_written_protocol_and_the_code_say_the_same_thing() -> None:
    """The provider is external, so its protocol is documentation first.

    Nothing in the repository type-checks ``fixtures/provider/README.md``, and prose that drifts from
    the implementation is worse than no prose: a reader would follow the document. So the document is
    held to the facts the code cannot restate on its own — the fault names it accepts, the states it
    can report, and the two rules that are easy to get backwards (unknown is not failed, not found is
    not failed either).
    """
    document = (REPO_ROOT / "fixtures" / "provider" / "README.md").read_text(encoding="utf-8")

    for fault in FAULTS:
        assert fault in document, f"the protocol document has to describe the {fault} fault"
    for state in (SUCCEEDED, FAILED, UNKNOWN, NOT_FOUND):
        assert state in document, f"the protocol document has to name the {state} state"
    assert "UNKNOWN 不是 FAILED" in document, "the distinction the money path depends on has to be written down"
    assert "operation_id" in document and "幂等" in document, (
        "the document has to say that the idempotency key comes from upstream"
    )
    assert "不对 Agent 可见" in document, "and that the provider credential is not the Agent's to see"


def test_money_is_counted_in_integer_minor_units(tmp_path: Path) -> None:
    """No float ever touches an amount (docs/engineering.md:9).

    A round-tripped float amount is how 2599 becomes 2598.9999999999995 in somebody's ledger, so the
    module must not contain float arithmetic at all — and the check is on the source, not on one call,
    because the failure would be in the branch a single test does not take.
    """
    source = (REPO_ROOT / "agent" / "src" / "resolveflow" / "provider_stub" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "float" not in source, "the provider stub must not mention float at all"
    result = request(RefundProviderStub(tmp_path / "provider.sqlite3"))
    assert isinstance(result.amount_minor, int) and not isinstance(result.amount_minor, bool)
