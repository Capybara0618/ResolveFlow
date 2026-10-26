"""Persisted requests must survive partial bursts without silent resend."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.trade_request_journal import RequestJournal, UnknownRequest, overlap


def test_recovery_keeps_completed_response_and_refuses_unknown_tail(tmp_path):
    journal = RequestJournal(tmp_path / "requests")
    ids = journal.prepare("/api/v1/shop/drafts/a/payment", "buyer", [({}, "same"), ({}, "same")])
    journal.start(ids[0])
    journal.finish(ids[0], {"status": 200, "body": {"attempt_id": "original", "name": "中文商品"}})
    reopened = RequestJournal(journal.folder, create=False)
    assert reopened.recover(ids[:1])[0]["body"]["attempt_id"] == "original"
    assert reopened.recover(ids[:1])[0]["body"]["name"] == "中文商品"
    with pytest.raises(UnknownRequest):
        reopened.recover(ids)
    with pytest.raises(ValueError, match="read-only"):
        reopened.prepare("/api/v1/shop/drafts/a/payment", "buyer", [({}, "new")])


def test_mismatched_or_truncated_completion_is_not_accepted(tmp_path):
    journal = RequestJournal(tmp_path / "requests")
    request = journal.prepare("/api/v1/shop/drafts/a/payment", "buyer", [({}, "key")])[0]
    target = journal.folder / request / "completed.json"
    target.write_text('{"request_id":"other","status":200}')
    with pytest.raises(ValueError):
        journal.recover([request])
    target.write_text('{"status":')
    with pytest.raises(ValueError):
        journal.recover([request])


def test_peak_is_interval_overlap_not_requested_thread_count():
    rows = [{"started_ns": 1, "finished_ns": 3}, {"started_ns": 3, "finished_ns": 5}]
    assert overlap(rows) == 1
    assert overlap([*rows, {"started_ns": 2, "finished_ns": 4}]) == 2
    with pytest.raises(ValueError):
        overlap([{"started_ns": 5, "finished_ns": 1}])


def test_real_process_exit_retains_each_completed_request(tmp_path):
    folder = tmp_path / "requests"
    source = str(Path(__file__).resolve().parents[3] / "scripts")
    code = '''import os,sys
sys.path.insert(0,sys.argv[1])
from evaluation.trade_request_journal import RequestJournal
j=RequestJournal(sys.argv[2])
ids=j.prepare('/api/v1/shop/cart/M-1001/items','buyer',[({},'a'),({},'b')])
j.start(ids[0]); j.finish(ids[0],{'status':200,'body':{'saved':True}})
j.start(ids[1]); os._exit(73)
'''
    result = subprocess.run([sys.executable, "-c", code, source, str(folder)], check=False)  # noqa: S603 -- fixed local test program
    assert result.returncode == 73
    journal = RequestJournal(folder, create=False)
    assert journal.recover(["000000"])[0]["body"] == {"saved": True}
    assert journal.audit()["unknown"] == ["000001"]


def test_auth_route_and_unregistered_token_never_enter_journal(tmp_path):
    journal = RequestJournal(tmp_path / "requests")
    with pytest.raises(ValueError):
        journal.prepare("/api/v1/auth/login", "buyer", [({"password": "secret"}, None)])
    with pytest.raises(ValueError, match="registered"):
        journal.actor("unregistered-token")
    assert list(journal.folder.glob("[0-9]*")) == []


def test_waiting_for_more_active_requests_is_explicit_not_reached(tmp_path):
    journal = RequestJournal(tmp_path / "requests")
    request = journal.prepare("/api/v1/shop/cart/M-1001/items", "buyer", [({}, "a")])[0]
    journal.start(request)
    with pytest.raises(TimeoutError, match="concurrency window"):
        journal.wait_active("/api/v1/shop/cart/M-1001/items", 2, timeout=.01)
    intent = json.loads((journal.folder / request / "intent.json").read_text())
    assert intent["actor"] == "buyer" and "token" not in intent
