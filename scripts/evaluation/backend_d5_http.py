"""D5 deterministic HTTP traffic and offline request-level scoring. Never sends model calls."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import math
import time
from collections import Counter
from urllib.parse import urlencode

import aiohttp

from evaluation.backend_d5_seed import literal


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def fixture_token(actor):
    """Local synthetic users still pass the production persisted-account/version checks."""
    now = int(time.time())
    claims = {
        "sub": actor,
        "aud": "resolveflow-user",
        "iss": "resolveflow-demo-identity",
        "iat": now,
        "exp": now + 86400,
        "identity_version": 0,
    }
    if actor.startswith("d5-buyer-"):
        claims.update(role="CUSTOMER", buyer_id="D5-B" + actor[-3:])
    elif actor in ("d5-merchant-0", "d5-merchant-1", "d5-merchant-2"):
        claims.update(
            role="MERCHANT_ADMIN", merchant_id="M-100" + str(int(actor[-1]) + 1)
        )
    else:
        raise ValueError("only explicitly seeded synthetic accounts")
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    unsigned = (
        encode(b'{"alg":"HS256","typ":"JWT"}')
        + "."
        + encode(json.dumps(claims).encode())
    )
    return (
        unsigned
        + "."
        + encode(
            hmac.digest(
                b"resolveflow-core-demo-identity-secret", unsigned.encode(), "sha256"
            )
        )
    )


def purchase_expected(oracle, buyer, store, status):
    rows = [
        r
        for r in oracle["purchases"]
        if r["buyer"] == buyer
        and (store is None or r["store"] == store)
        and (status is None or r["status"] == status)
    ]
    # All fixture created_at values are identical. Native shard order is id DESC;
    # stable cross-shard merge orders tied timestamps by store ASC.
    rows.sort(key=lambda r: r["id"], reverse=True)
    rows.sort(key=lambda r: r["store"])
    return rows[:24]


async def fetch(session, base, spec, tokens):
    started = time.perf_counter_ns()
    status, error, body, raw = 0, None, None, b""
    try:
        headers = {"Accept": "application/json"}
        if spec.get("actor"):
            headers["Authorization"] = "Bearer " + tokens[spec["actor"]]
        async with session.get(base + spec["path"], headers=headers) as response:
            status = response.status
            raw = await response.read()
        body = json.loads(raw)
    except (aiohttp.ClientError, TimeoutError, ValueError, OSError) as exc:
        error = type(exc).__name__
    elapsed = (time.perf_counter_ns() - started) / 1e6
    answer = {
        "status": status,
        "elapsed_ms": elapsed,
        "error": error,
        "bytes": len(raw),
    }
    if body is not None:
        answer["body_sha256"] = digest(body)
    answer["correct"] = (
        status == 200
        and error is None
        and answer.get("body_sha256") == spec.get("body_sha256")
    )
    if not answer["correct"] and status == 200 and error is None:
        answer["error"] = "PROJECTION_MISMATCH"
    return answer, body


def session(concurrency):
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=3),
        connector=aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency),
        trust_env=False,
        auto_decompress=True,
    )


async def freeze_requests(settings):
    """Independent fixture/SQL assertions precede full baseline projection freezing."""
    oracle = json.loads(
        (settings.folder / "dataset-oracle.json").read_text(encoding="utf-8")
    )
    base = f"http://127.0.0.1:{settings.load()['ports']['gateway']}"
    specs, profiles = {}, {"P1": [], "P2": [], "P3": []}
    tokens = {
        f"d5-buyer-{i:03d}": fixture_token(f"d5-buyer-{i:03d}") for i in range(50)
    }
    tokens.update(
        {f"d5-merchant-{i}": fixture_token(f"d5-merchant-{i}") for i in range(2)}
    )

    async with session(2) as client:
        for merchant in range(2):
            ids = settings.sql(
                f"SELECT case_id FROM case_db.aftersale_case WHERE merchant_id='M-100{merchant + 1}' AND status='PENDING_REVIEW' ORDER BY updated_at DESC,case_id DESC LIMIT 40;"
            ).splitlines()
            path = "/api/v1/review/cases?view=REVIEW&scope=PUBLIC&limit=20"
            for page in range(2 if merchant == 0 else 1):
                key = f"workspace-{merchant}-{page}"
                spec = {"actor": f"d5-merchant-{merchant}", "path": path}
                result, body = await fetch(client, base, spec, tokens)
                assert result["status"] == 200, (key, result, body)
                assert [r["case_id"] for r in body["items"]] == ids[
                    page * 20 : (page + 1) * 20
                ], key
                assert all(r["status"] == "PENDING_REVIEW" for r in body["items"])
                assert body["counts"]["public"] == 2000
                spec["body_sha256"] = digest(body)
                specs[key] = spec
                path += "&cursor=" + body["page"]["next_cursor"]
        profiles["P1"] = ["workspace-0-0"] * 8 + ["workspace-0-1", "workspace-1-0"]
        for buyer in range(50):
            actor = f"d5-buyer-{buyer:03d}"
            for status in (None, "PAID", "WAITING_PAYMENT"):
                store = None if buyer % 2 == 0 else "M-100" + str(buyer % 3 + 1)
                query = {"limit": 24}
                if status:
                    query["status"] = status
                if store:
                    query["store_id"] = store
                key = f"purchase-{buyer}-{status or 'ALL'}"
                spec = {
                    "actor": actor,
                    "path": "/api/v1/shop/purchases?" + urlencode(query),
                }
                result, body = await fetch(client, base, spec, tokens)
                assert result["status"] == 200, (key, result, body)
                expected = purchase_expected(oracle, buyer, store, status)
                assert [r["purchase_id"] for r in body["items"]] == [
                    r["id"] for r in expected
                ], key
                for row, want in zip(body["items"], expected, strict=True):
                    assert (row["store_id"], row["status"], row["total_amount"]) == (
                        want["store"],
                        want["status"],
                        want["total"],
                    ), key
                    assert (
                        sum(line["line_amount"] for line in row["lines"])
                        == row["total_amount"]
                    )
                    assert sorted(
                        (line["sku"], line["quantity"], line["line_amount"])
                        for line in row["lines"]
                    ) == sorted(
                        (line["id"], line["quantity"], line["amount"])
                        for line in want["lines"]
                    ), key
                spec.update(
                    body_sha256=digest(body),
                    empty=not expected,
                    expected_count=len(expected),
                )
                specs[key] = spec
                profiles["P2"] += [key] * (6 if status is None else 2)
        for product in oracle["products"]:
            key = "review-" + product["id"]
            spec = {"path": f"/api/v1/shop/products/{product['id']}/reviews?limit=10"}
            result, body = await fetch(client, base, spec, tokens)
            assert result["status"] == 200, (key, result, body)
            ids = [
                int(r)
                for r in settings.sql(
                    "SELECT review_id FROM commerce_db.product_review WHERE product_id="
                    + literal(product["id"])
                    + " ORDER BY review_id DESC LIMIT 10;"
                ).splitlines()
            ]
            assert [r["review_id"] for r in body["items"]] == ids
            assert all(r["product_id"] == product["id"] for r in body["items"])
            assert body["summary"] == {"count": 200, "average": 3.0, "stars": [40] * 5}
            spec["body_sha256"] = digest(body)
            specs[key] = spec
        # A 1450-slot cycle contains exactly 80% hot, 20% evenly spread over 29 products.
        products = ["review-" + p["id"] for p in oracle["products"]]
        for i in range(290):
            profiles["P3"] += [products[0]] * 4 + [products[1 + i % 29]]
    return {
        "seed": 42,
        "specs": specs,
        "profiles": profiles,
        "empty_p2_slots": sum(specs[k]["empty"] for k in profiles["P2"]),
        "p2_slots": len(profiles["P2"]),
        "projection_source": "full initial application response after independent fixture/SQL assertions; candidate must match all fields",
    }


def traffic_key(cohort, profile, sequence):
    choices = cohort["profiles"][profile]
    # Rotation is a permutation (step 7 is coprime with 10,500,1450).
    return choices[(sequence * 7 + 42) % len(choices)]


async def window(base, cohort, profile, concurrency, seconds, output):
    tokens = {
        s["actor"]: fixture_token(s["actor"])
        for s in cohort["specs"].values()
        if s.get("actor")
    }
    sequence = 0
    started = time.perf_counter()
    cpu = time.process_time()
    deadline = started + seconds
    # A single writer in the event loop preserves unique request IDs without a thread lock.
    with gzip.open(output, "xt", encoding="utf-8", compresslevel=1) as handle:
        async with session(concurrency) as client:

            async def worker():
                nonlocal sequence
                while time.perf_counter() < deadline:
                    number = sequence
                    sequence += 1
                    key = traffic_key(cohort, profile, number)
                    offset = time.perf_counter() - started
                    result, _ = await fetch(client, base, cohort["specs"][key], tokens)
                    row = {
                        "sequence": number,
                        "key": key,
                        "offset_seconds": offset,
                        **result,
                    }
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")

            await asyncio.gather(*(worker() for _ in range(concurrency)))
    return {
        "requests": sequence,
        "elapsed_seconds": time.perf_counter() - started,
        "client_cpu_seconds": time.process_time() - cpu,
        "target_seconds": seconds,
        "concurrency": concurrency,
    }


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


def score(path, cohort, profile, metadata):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = traffic_key(cohort, profile, row["sequence"])
            if row["key"] != key:
                raise ValueError("traffic sequence changed")
            expected = (
                row["status"] == 200
                and row.get("error") is None
                and row.get("body_sha256") == cohort["specs"][key]["body_sha256"]
            )
            if row["correct"] != expected or row["elapsed_ms"] < 0:
                raise ValueError("request scoring mismatch")
            rows.append(row)
    ids = [r["sequence"] for r in rows]
    if len(ids) != metadata["requests"] or sorted(ids) != list(range(len(ids))):
        raise ValueError("missing or duplicate request")
    if metadata["elapsed_seconds"] < metadata["target_seconds"]:
        raise ValueError("shortened measurement window")
    okay = [r["elapsed_ms"] for r in rows if r["correct"]]
    failed = [r["elapsed_ms"] for r in rows if not r["correct"]]
    elapsed = metadata["elapsed_seconds"]
    return {
        "total": len(rows),
        "success": len(okay),
        "failed": len(failed),
        "statuses": dict(Counter(str(r["status"]) for r in rows)),
        "errors": dict(Counter(r["error"] for r in rows if r.get("error"))),
        "success_rps": len(okay) / elapsed,
        "total_rps": len(rows) / elapsed,
        "success_p50_ms": percentile(okay, 0.5),
        "success_p95_ms": percentile(okay, 0.95),
        "success_p99_ms": percentile(okay, 0.99),
        "failure_p95_ms": percentile(failed, 0.95),
        "all_p95_ms": percentile([r["elapsed_ms"] for r in rows], 0.95),
    }
