"""A lost success response is an actual socket loss backed by a durable receipt."""

import http.client
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_provider import Provider


def test_actual_socket_loss_and_delayed_query_retain_success(tmp_path):
    provider = Provider(tmp_path / "provider.sqlite3", 0)
    try:
        provider.lose_response.add("lost-op")
        provider.visibility_delay_seconds = 10
        client = http.client.HTTPConnection("127.0.0.1", provider.server.server_port, timeout=3)
        client.request("POST", "/provider/v1/refunds", json.dumps({"operation_id": "lost-op", "line_id": "line-a",
                       "amount_minor": 2599, "currency": "CNY"}), {"Content-Type": "application/json"})
        with pytest.raises(http.client.RemoteDisconnected):
            client.getresponse()
        client.close()
        assert provider.stub.query_refund("lost-op").state == "SUCCEEDED"
        assert provider.stub.attempts("lost-op") == 1
        query = http.client.HTTPConnection("127.0.0.1", provider.server.server_port, timeout=3)
        query.request("GET", "/provider/v1/refunds/lost-op")
        response = query.getresponse()
        assert response.status == 404
        assert json.loads(response.read())["state"] == "NOT_FOUND"
        query.close()
    finally:
        provider.close()
    restarted = Provider(tmp_path / "provider.sqlite3", 0)
    try:
        assert restarted.stub.query_refund("lost-op").state == "SUCCEEDED"
        assert restarted.stub.attempts("lost-op") == 1
    finally:
        restarted.close()


def test_no_receipt_unknown_control_does_not_write_success(tmp_path):
    provider = Provider(tmp_path / "provider.sqlite3", 0)
    try:
        provider.no_receipt.add("unknown-op")
        client = http.client.HTTPConnection("127.0.0.1", provider.server.server_port, timeout=3)
        client.request("POST", "/provider/v1/refunds", json.dumps({"operation_id": "unknown-op", "line_id": "line-b",
                       "amount_minor": 1000, "currency": "CNY"}), {"Content-Type": "application/json"})
        response = client.getresponse()
        assert response.status == 200 and json.loads(response.read())["state"] == "UNKNOWN"
        client.close()
        assert provider.stub.query_refund("unknown-op").state == "NOT_FOUND"
        assert provider.stub.attempts("unknown-op") == 0
        assert [r["stage"] for r in provider.trace] == ["request", "no_receipt"]
    finally:
        provider.close()
