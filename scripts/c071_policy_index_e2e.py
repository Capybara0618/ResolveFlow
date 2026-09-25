"""C07.1 end to end: real case-service → authoritative bundles → READY index → both retrieval paths.

Why this exists as well as the unit/integration tests. Those tests prove the index's *behaviour* against rows
they wrote themselves with hashes they chose. They cannot prove the thing C07.1's design actually rests on:
that the text and the hashes this side indexes are **Java's**, fetched from the running service. A test that
fabricates a ``ServedBundle`` would pass just as happily if Java's ``content_hash`` construction had drifted,
or if the route stopped publishing ``merchant_id`` — which is the whole reason the cross-language comparison in
``scripts/policy_index_ingest.py`` exists.

So this driver does, in order, on the real services:

1. start the real ``case-service`` (it needs MySQL, which compose provides);
2. run the **controlled policy import** against ``fixtures/policies/bundles`` — the same command an operator
   runs, so the shipped fixtures are proven importable;
3. for every bundle, ask case-service for it over ``GET /internal/v1/policies/{bundle_id}`` with a service token
   carrying ``policy:read``, and **stop if this side's recomputed rule hashes disagree** with Java's;
4. build the index from those served bundles and mark each generation READY;
5. run both retrieval paths over the frozen 40-query set, and check the two properties the acceptance criteria
   name: a run pinned to an unindexed manifest is **refused** rather than given another version, and no hit ever
   comes from another merchant or version.

The tokens are signed here with the demo secret, exactly as ``scripts/e2e_harness_java_tools.py`` does: this is
the identity the internal surface requires of the caller, not a credential this script invents.

Usage (compose MySQL must be up; the script starts the Java service itself)::

    & agent\\.venv\\Scripts\\python.exe scripts\\c071_policy_index_e2e.py
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

CASE_PORT = 8083
JWT_SECRET = "resolveflow-core-demo-identity-secret"
SERVICE_ISSUER = "resolveflow-demo-identity"
SERVICE_AUDIENCE = "resolveflow-service"

#: The bundles the fixtures ship, in the order the import reads them. Written out rather than globbed so a
#: fixture that stopped being importable is a missing-name failure here rather than a silently shorter run.
BUNDLES = [
    "policy-logistics-2026.08",
    "policy-logistics-2026.09",
    "policy-damage-2026.08",
    "policy-damage-2026.09",
]

#: The bundle a "pinned to a version nobody indexed" check uses. Deliberately not the seed data's: a real hash
#: would be found, and the point is the honest refusal.
UNINDEXED_MANIFEST_HASH = "f" * 64


class Report:
    """A step log that a failure aborts, so a red run says which step refused rather than only that it did."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures = 0

    def step(self, description: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            self.failures += 1
        suffix = f"  — {detail}" if detail else ""
        line = f"[{mark}] {description}{suffix}"
        self.lines.append(line)
        print(line, flush=True)

    def note(self, text: str) -> None:
        self.lines.append(f"       {text}")
        print(f"       {text}", flush=True)

    def section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(f"== {title} ==")
        print(f"\n== {title} ==", flush=True)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_service_token(subject: str, *, scope: str | None = None, seconds: int = 600) -> str:
    """A service token signed with the demo secret — the identity the ``/internal`` surface requires."""
    issued = int(time.time())
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": SERVICE_AUDIENCE,
        "iss": SERVICE_ISSUER,
        "iat": issued,
        "exp": issued + seconds,
    }
    if scope is not None:
        claims["scope"] = scope
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64(json.dumps(claims, ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


def get(url: str, token: str | None = None, *, timeout: float = 15.0) -> tuple[int, Any]:
    request = urllib.request.Request(url)  # noqa: S310 - our own base URL
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, raw.decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return 0, f"{error.reason}"


def resolve_java() -> str:
    """A JDK **21+** ``java``, resolved rather than taken from ``PATH``.

    ``java`` on this machine is 17 while the project builds for 21 (``docs/engineering.md``; ``scripts/doctor.ps1``
    warns about exactly this). The first version of this driver used ``PATH``'s ``java``, and the service died with
    ``UnsupportedClassVersionError`` — which reads as a broken jar rather than as the wrong interpreter. The search
    order matches ``scripts/verify.ps1``'s ``Resolve-JavaHome`` so the two cannot disagree about which JDK is used.
    """
    candidates: list[pathlib.Path] = []
    for root in (pathlib.Path.home() / ".jdks", pathlib.Path("C:/Program Files/Eclipse Adoptium"),
                 pathlib.Path("C:/Program Files/Java")):
        if root.is_dir():
            candidates.extend(sorted(path for path in root.iterdir() if path.is_dir()))
    configured = os.environ.get("JAVA_HOME")
    if configured:
        candidates.insert(0, pathlib.Path(configured))

    for home in candidates:
        java = home / "bin" / "java.exe"
        if not java.is_file():
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - a resolved JDK path, not caller input
                [str(java), "-version"], capture_output=True, text=True, timeout=20
            )
        except (OSError, subprocess.SubprocessError):
            continue
        reported = completed.stderr or completed.stdout
        match = re.search(r'version "(\d+)', reported)
        if match and int(match.group(1)) >= 21:
            return str(java)
    raise SystemExit(
        "no JDK 21+ found under ~/.jdks, C:/Program Files/Eclipse Adoptium, C:/Program Files/Java or JAVA_HOME. "
        "Run scripts/doctor.ps1 to see what this machine has."
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_health(url: str, process: subprocess.Popen[Any], seconds: float = 90.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        status, _ = get(url, timeout=3)
        if status == 200:
            return True
        time.sleep(1)
    return False


def jar_for() -> pathlib.Path:
    """The built case-service jar, or a clear instruction rather than a stack trace."""
    target = REPO_ROOT / "java" / "case-service" / "target"
    candidates = sorted(target.glob("case-service-*.jar")) if target.is_dir() else []
    jars = [path for path in candidates if not path.name.endswith("-sources.jar")]
    if not jars:
        raise SystemExit(
            f"no case-service jar under {target}. Build it first:\n"
            f"  cd java; .\\mvnw.cmd -B -DskipTests package"
        )
    return jars[-1]


def classpath_for(java: str) -> str:
    """The case-service runtime classpath, built by Maven and used to run the application class directly.

    Running the **class** rather than the fat jar is deliberate, and it is the lesson of two failed runs. The
    repackaged jar embeds ``shared-kernel`` from the local Maven repository, and that artifact can be stale (a
    3.7 KB ``shared-kernel`` with no ``JwtCodec`` was installed in this machine's ``~/.m2``); the service then dies
    with ``NoClassDefFoundError``, which reads as a broken policy change rather than as a stale dependency. The
    classpath Maven resolves is the reactor's own output, so what this driver exercises is what the tests exercise.
    """
    maven = REPO_ROOT / "java" / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    output = REPO_ROOT / "tmp" / "c071-probe" / "case-service-classpath.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(  # noqa: S603 - a fixed command built from our own paths
        [
            str(maven),
            "-B",
            "-q",
            "-pl",
            "case-service",
            "dependency:build-classpath",
            f"-Dmdep.outputFile={output}",
        ],
        cwd=str(REPO_ROOT / "java"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not output.is_file():
        raise SystemExit(f"could not build the case-service classpath: {completed.stderr[-400:]}")
    classes = REPO_ROOT / "java" / "case-service" / "target" / "classes"
    return f"{output.read_text(encoding='utf-8').strip()}{os.pathsep}{classes}"


def run_policy_import(java: str, classpath: str, report: Report) -> bool:
    """The controlled policy import, as its own one-shot process.

    ``--spring.main.web-application-type=none`` is what the fixtures' README documents, and it is not optional:
    ``PolicyImportCommand`` ends the process with ``System.exit`` so an import that refused a file exits non-zero
    for whichever pipeline ran it. Started as a *web* service, that exit kills the server seconds after Tomcat
    comes up — which is exactly what happened on the first attempt at this driver, and it looks like a service
    that cannot start.
    """
    completed = subprocess.run(  # noqa: S603 - a fixed command built from our own paths
        [
            java,
            "-cp",
            classpath,
            "com.resolveflow.caseservice.CaseServiceApplication",
            "--spring.main.web-application-type=none",
            "--resolveflow.policy.import-dir=fixtures/policies/bundles",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    imported = [line for line in (completed.stdout or "").splitlines() if "policy import:" in line]
    detail = imported[0].split("policy import:", 1)[1].strip() if imported else (completed.stderr or "")[-200:]
    report.step("the controlled policy import accepted every shipped fixture", completed.returncode == 0, detail)
    return completed.returncode == 0


def main(argv: list[str] | None = None) -> int:
    # The report is read by a person and it carries Chinese policy text, so the output has to be UTF-8 whatever
    # the console's code page is. Without this, printing a hit's text raised UnicodeEncodeError *after* every
    # check had passed, which reads as a failing run. `errors="replace"` keeps a genuinely unprintable console
    # from turning a result into a crash — the written report is the record.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=None, help="write the report here as well as to stdout")
    parser.add_argument("--skip-eval", action="store_true", help="stop after the index is READY")
    parser.add_argument(
        "--embed",
        action="store_true",
        help=(
            "build dense generations with the real embedding model, instead of a lexical-only index. Slower, "
            "and it is what the dense numbers in the report come from."
        ),
    )
    arguments = parser.parse_args(argv)

    started = dt.datetime.now(dt.UTC)
    report = Report()
    report.lines.append(f"C07.1 policy index end to end · started {started.isoformat()}")
    log_dir = REPO_ROOT / "reports" / "c071-policy-index"
    log_dir.mkdir(parents=True, exist_ok=True)

    from resolveflow.policies import PolicyIndex, ServedBundle
    from resolveflow.runtime.db import Database, default_dsn

    jar = jar_for()
    java = resolve_java()
    classpath = classpath_for(java)
    database = Database(default_dsn())
    database.migrations()
    index = PolicyIndex(database)

    log = (log_dir / "case-service-e2e.log").open("w", encoding="utf-8", errors="replace")
    process: subprocess.Popen[Any] | None = None
    try:
        report.section("real services")
        report.note(f"jdk {java}")
        report.note(f"running {jar.name} from {REPO_ROOT / 'java' / 'case-service' / 'target' / 'classes'}")
        if not run_policy_import(java, classpath, report):
            _emit(report, arguments.report)
            return 1

        process = subprocess.Popen(  # noqa: S603 - a fixed command built from our own paths
            [
                java,
                "-cp",
                classpath,
                "com.resolveflow.caseservice.CaseServiceApplication",
                f"--server.port={CASE_PORT}",
            ],
            cwd=str(REPO_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "JAVA_HOME": str(pathlib.Path(java).parent.parent)},
        )
        healthy = wait_health(f"http://127.0.0.1:{CASE_PORT}/actuator/health", process)
        report.step("case-service started", healthy, f"port {CASE_PORT}")
        if not healthy:
            report.note(f"see {log.name}")
            _emit(report, arguments.report)
            return 1

        report.section("authoritative read (Java owns the text and the hashes)")
        token = mint_service_token("agent-service", scope="policy:read")
        served: list[dict[str, Any]] = []
        for bundle_id in BUNDLES:
            status, payload = get(f"http://127.0.0.1:{CASE_PORT}/internal/v1/policies/{bundle_id}", token)
            if status != 200 or not isinstance(payload, dict):
                report.step(f"GET /internal/v1/policies/{bundle_id}", False, f"HTTP {status}: {payload}")
                continue
            served.append(payload)
            report.step(
                f"GET /internal/v1/policies/{bundle_id}",
                True,
                f"merchant={payload.get('merchant_id')} version={payload.get('version')} "
                f"rules={len(payload.get('rules') or [])} hash={str(payload.get('manifest_hash'))[:16]}…",
            )

        # The scope is enforced on this route since AS02.3's security sub-step, so a token without it must be
        # refused. Asserted here because "the read needs policy:read" is a claim this driver depends on.
        status, _ = get(
            f"http://127.0.0.1:{CASE_PORT}/internal/v1/policies/{BUNDLES[0]}",
            mint_service_token("agent-service", scope="commerce:read"),
        )
        report.step("the route refuses a token without policy:read", status == 403, f"HTTP {status}")

        problems: list[str] = []
        for payload in served:
            problems.extend(_hash_disagreements(payload))
        report.step(
            "this side's recomputed content_hash agrees with Java's for every rule",
            not problems,
            "; ".join(problems[:5]) if problems else f"{sum(len(p.get('rules') or []) for p in served)} rules",
        )
        if problems or not served:
            _emit(report, arguments.report)
            return 1

        report.section("index")
        the_embedder = None
        if arguments.embed:
            from resolveflow.policies import embedder

            the_embedder = embedder()
            started_at = time.time()
            the_embedder.embed(["预热"])
            report.step(
                "the dense embedder loaded",
                True,
                f"{the_embedder.model} @ {the_embedder.revision[:12]}… {the_embedder.dimension} dims, "
                f"{time.time() - started_at:.1f}s to load and warm up",
            )
        for payload in served:
            started_at = time.time()
            ingestion = index.build(_served(payload), embedder=the_embedder, replace=True)
            report.step(
                f"indexed {ingestion.bundle_id}",
                ingestion.chunk_count > 0,
                f"generation={ingestion.generation_id[:12]} chunks={ingestion.chunk_count} "
                f"lineage={ingestion.lineage_hash[:16]}… {time.time() - started_at:.1f}s",
            )
        if the_embedder is None:
            report.note(
                "dense vectors were NOT built (no --embed): this run checks the read, the hashes, the READY gate "
                "and the filters. The dense numbers in the report come from a run with --embed."
            )
        else:
            report.note(
                f"each generation records the embedding it used ({the_embedder.model} @ "
                f"{the_embedder.revision}), so a model change is a new generation rather than a silent change of "
                "meaning for stored vectors."
            )

        report.section("the acceptance properties")
        _check_gate(report, index, served)
        _check_filters(report, index, served)

        if not arguments.skip_eval:
            report.section("both retrieval paths over the frozen query set")
            _eval_paths(report, dense=arguments.embed)

        report.lines.append("")
        report.lines.append(
            f"RESULT: {'PASSED' if report.failures == 0 else f'FAILED ({report.failures} checks)'}"
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()
        database.close()

    report.lines.append(f"finished at {dt.datetime.now(dt.UTC).isoformat()}")
    _emit(report, arguments.report)
    return 0 if report.failures == 0 else 1


def _served(payload: dict[str, Any]) -> Any:
    from resolveflow.policies import served_bundle_of

    return served_bundle_of(payload)


def _hash_disagreements(payload: dict[str, Any]) -> list[str]:
    """Every rule whose Java-served hash differs from this side's recomputation.

    This is the cross-language check: ``docs/core-contracts.md:56`` fixes one construction, and the two
    implementations agreeing is the evidence. A disagreement means a citation this side hands out is one Java
    will not accept, so it must stop the run.
    """
    from resolveflow.policies import chunks_of_bundle

    bundle_id = str(payload.get("bundle_id"))
    rules = payload.get("rules") or []
    problems: list[str] = []
    for chunk, rule in zip(chunks_of_bundle(bundle_id, rules), rules, strict=True):
        if rule.get("content_hash") != chunk.content_hash:
            problems.append(f"{bundle_id}/{chunk.rule_id}: Java {rule.get('content_hash')} vs {chunk.content_hash}")
    return problems


def _check_gate(report: Report, index: Any, served: list[dict[str, Any]]) -> None:
    """索引未就绪不搜旧版本: a pinned-but-unindexed manifest is refused, not answered from another version."""
    from resolveflow.policies import PolicyIndexNotReadyError

    bundle = _served(served[0])
    try:
        index.search(
            merchant_id=bundle.merchant_id,
            bundle_ids=[bundle.bundle_id],
            manifest_hash=UNINDEXED_MANIFEST_HASH,
            query="承运商说件丢了",
            path="bm25",
        )
        report.step(
            "a run pinned to an unindexed manifest is refused rather than given another version",
            False,
            "the search returned instead of refusing",
        )
    except PolicyIndexNotReadyError as refusal:
        report.step(
            "a run pinned to an unindexed manifest is refused rather than given another version",
            "no READY generation" in str(refusal),
            str(refusal)[:150],
        )

    ready = index.search(
        merchant_id=bundle.merchant_id,
        bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash,
        query="承运商说件丢了",
        path="bm25",
    )
    report.step(
        "the same run with its real pinned manifest is answered",
        len(ready) > 0,
        f"{len(ready)} hit(s), first {ready[0].bundle_id}/{ready[0].rule_id}" if ready else "no hits",
    )


def _check_filters(report: Report, index: Any, served: list[dict[str, Any]]) -> None:
    """Every hit must come from the pinned bundle and version — the merchant/version filter, measured."""
    violations = 0
    checked = 0
    for payload in served:
        bundle = _served(payload)
        for query in ("丢失", "签收", "退款", "破损", "扫描"):
            checked += 1
            hits = index.search(
                merchant_id=bundle.merchant_id,
                bundle_ids=[bundle.bundle_id],
                manifest_hash=bundle.manifest_hash,
                query=query,
                path="bm25",
            )
            for hit in hits:
                if hit.bundle_id != bundle.bundle_id or hit.manifest_hash != bundle.manifest_hash:
                    violations += 1
                if hit.merchant_id != bundle.merchant_id:
                    violations += 1
    report.step(
        "no hit came from another bundle, version or merchant",
        violations == 0,
        f"{checked} searches over the indexed bundles, {violations} violation(s)",
    )


def _eval_paths(report: Report, *, dense: bool) -> None:
    """Run the frozen query set through both paths here, so this driver's result does not depend on a second run.

    It shells out to ``scripts/policy_search_eval.py`` rather than reimplementing the metrics: one definition of
    Recall@5/MRR@5, used by the report a reader checks and by this end-to-end driver.
    """
    name = "retrieval-eval-both" if dense else "retrieval-eval-bm25"
    report_path = REPO_ROOT / "reports" / "c071-policy-index" / f"{name}.txt"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "policy_search_eval.py"),
        "--report",
        str(report_path),
    ]
    if not dense:
        # A generation built without vectors cannot answer a dense search — the index refuses rather than
        # falling back — so asking for the dense half here would report a refusal as a retrieval failure.
        command.append("--skip-dense")
    completed = subprocess.run(  # noqa: S603 - a fixed command built from our own paths
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = [line for line in completed.stdout.splitlines() if line.strip().startswith(("dev", "test", "all"))]
    label = "both paths" if dense else "BM25 baseline"
    report.step(
        f"{label} over the frozen 40 queries",
        completed.returncode == 0,
        "; ".join(tail) if tail else f"exit {completed.returncode}: {completed.stderr[-200:]}",
    )
    report.note(f"full evaluation written to {report_path.relative_to(REPO_ROOT)}")


def _emit(report: Report, path: str | None) -> None:
    document = "\n".join(report.lines)
    if path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document + "\n", encoding="utf-8")
        print(f"\nwrote {target}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
