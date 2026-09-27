"""Authenticated smoke of the four-process core Compose profile."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"


def request(path: str, *, body: dict[str, str] | None = None,
            token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main() -> None:
    deadline = time.monotonic() + 180
    while True:
        try:
            status, health = request("/actuator/health")
            if status == 200 and health.get("status") == "UP":
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError("core Gateway did not become healthy")
        time.sleep(1)
    status, reviewer = request("/api/v1/auth/login", body={
        "username": "demo-reviewer", "password": "demo-pass-1003"})
    assert status == 200 and reviewer.get("role") == "REVIEWER", (status, reviewer)
    status, customer = request("/api/v1/auth/login", body={
        "username": "demo-customer", "password": "demo-pass-1001"})
    assert status == 200 and customer.get("role") == "CUSTOMER", (status, customer)
    status, queue = request("/api/v1/review/cases?limit=20", token=str(reviewer["access_token"]))
    assert status == 200 and isinstance(queue.get("items"), list), (status, queue)
    status, denial = request("/api/v1/review/cases?limit=20", token=str(customer["access_token"]))
    assert status == 403 and denial.get("code") == "FORBIDDEN_SCOPE", (status, denial)
    print("core gateway health, login, scoped review queue and customer denial: PASS")


if __name__ == "__main__":
    main()
