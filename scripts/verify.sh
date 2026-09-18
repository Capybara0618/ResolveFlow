#!/usr/bin/env bash
# Linux/macOS equivalent of scripts/verify.ps1 — the entry point CI uses.
#
# Same suites, same exit semantics, same report location. Must stay in step with
# the PowerShell version; if one gains a step, the other gains it too.
#
# Suites owned by a later task report NOT IMPLEMENTED and exit 2 rather than
# passing vacuously.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$REPO_ROOT/reports/verify"
mkdir -p "$REPORT_DIR"

SUITE="all-offline"
MODE="mock"
SEED="42"
CASE_FILTER=""

while [ $# -gt 0 ]; do
    case "$1" in
        --suite|-Suite) SUITE="${2:?suite value required}"; shift 2 ;;
        --mode|-Mode)   MODE="${2:?mode value required}"; shift 2 ;;
        --seed|-Seed)   SEED="${2:?seed value required}"; shift 2 ;;
        --case|-Case)   CASE_FILTER="${2:?case value required}"; shift 2 ;;
        -h|--help)
            cat <<'USAGE'
usage: scripts/verify.sh [--suite <name>] [--mode mock|live] [--seed N] [--case <filter>]

suites: doctor format unit smoke all-offline
        contracts system faults performance agent-eval rag-eval harness harness-eval
USAGE
            exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_PATH="$REPORT_DIR/${STAMP}-${SUITE}.txt"

TRANSCRIPT=()
FAILURES=()

both()  { echo "$1"; TRANSCRIPT+=("$1"); }
head2() { both ""; both "== $1"; }

# Suites owned by a later task. Listing them here keeps the refusal explicit.
not_implemented_owner() {
    case "$1" in
        contracts)    echo "T02 契约固化与跨语言fixture" ;;
        system)       echo "T14 case执行编排与退款闭环" ;;
        faults)       echo "T29 故障实验完整矩阵" ;;
        performance)  echo "T30 性能与RAG对照" ;;
        rag-eval)     echo "T30 性能与RAG对照" ;;
        agent-eval)   echo "T24/T31 基线与live评测" ;;
        harness)      echo "T38 隔离回放与GH验收" ;;
        harness-eval) echo "T39 Harness消融" ;;
        *)            echo "" ;;
    esac
}

# Suites this script actually implements today.
is_implemented_suite() {
    case "$1" in
        doctor|format|unit|smoke|all-offline) return 0 ;;
        *) return 1 ;;
    esac
}

is_known_suite() {
    is_implemented_suite "$1" || [ -n "$(not_implemented_owner "$1")" ]
}

resolve_java_home() {
    for candidate in "${JAVA_HOME:-}" "$HOME/.jdks"/* /usr/lib/jvm/* /opt/java/*; do
        [ -n "$candidate" ] || continue
        [ -x "$candidate/bin/java" ] || continue
        major="$("$candidate/bin/java" -version 2>&1 | head -1 | sed -n 's/.*version "\([0-9]*\).*/\1/p')"
        if [ -n "$major" ] && [ "$major" -ge 21 ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

run_step() {
    local name="$1" command="$2"
    shift 2

    both "  -- $name"
    both "     \$ $command"

    local started elapsed status
    started="$(date +%s)"
    if "$@"; then
        status=0
    else
        status=$?
    fi

    elapsed=$(( $(date +%s) - started ))
    if [ "$status" -eq 0 ]; then
        both "     PASS (${elapsed}s)"
        return 0
    fi

    both "     FAIL (exit ${status}, ${elapsed}s)"
    FAILURES+=("$name")
    return 1
}

http_up() {
    local url="$1" timeout="${2:-90}" deadline
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if curl -fsS --max-time 5 "$url" 2>/dev/null | grep -q 'UP'; then
            return 0
        fi
        sleep 2
    done
    return 1
}

both "ResolveFlow verify"
both "  suite : $SUITE"
both "  mode  : $MODE"
both "  seed  : $SEED"
[ -n "$CASE_FILTER" ] && both "  case  : $CASE_FILTER"
both "  report: $REPORT_PATH"

# An unrecognised suite must fail loudly. Otherwise a typo (or a suite someone
# renamed) would run zero steps and still report PASSED — exactly the
# "skip masquerading as pass" failure docs/engineering.md 5 forbids.
if ! is_known_suite "$SUITE"; then
    both ""
    both "UNKNOWN SUITE: '$SUITE' is not a suite this script implements."
    both "Known suites: doctor format unit smoke all-offline"
    both "Deferred to a later task: contracts system faults performance agent-eval rag-eval harness harness-eval"
    both "Refusing to report success for a suite that ran nothing."
    printf '%s\n' "${TRANSCRIPT[@]}" > "$REPORT_PATH"
    exit 64
fi

owner="$(not_implemented_owner "$SUITE")"
if [ -n "$owner" ]; then
    both ""
    both "NOT IMPLEMENTED: suite '$SUITE' belongs to $owner."
    both "Refusing to report success for a suite that ran nothing."
    printf '%s\n' "${TRANSCRIPT[@]}" > "$REPORT_PATH"
    exit 2
fi

JAVA_HOME_21="$(resolve_java_home)" || {
    echo "JDK 21 not found; run scripts/doctor.sh for detail." >&2
    exit 1
}
export JAVA_HOME="$JAVA_HOME_21"

if [ "$SUITE" = "doctor" ]; then
    head2 "doctor"
    run_step "doctor" "bash scripts/doctor.sh" bash "$REPO_ROOT/scripts/doctor.sh" || true
fi

if [ "$SUITE" = "format" ] || [ "$SUITE" = "all-offline" ]; then
    head2 "format"
    run_step "java-spotless" "java/mvnw -f java/pom.xml -B spotless:check" \
        "$REPO_ROOT/java/mvnw" -f java/pom.xml -B -ntp spotless:check || true
    run_step "python-ruff" "uv run --project agent ruff check agent/src agent/tests" \
        uv run --project agent --frozen ruff check agent/src agent/tests || true
    run_step "python-mypy" "uv run --project agent mypy agent/src" \
        uv run --project agent --frozen mypy agent/src || true
    if [ -d "$REPO_ROOT/web/node_modules" ]; then
        run_step "web-typecheck" "pnpm --dir web typecheck" pnpm --dir web typecheck || true
    else
        both "  -- web-typecheck SKIPPED: web/node_modules missing (run pnpm --dir web install)"
        FAILURES+=("web-typecheck-skipped")
    fi
fi

if [ "$SUITE" = "unit" ] || [ "$SUITE" = "all-offline" ]; then
    head2 "unit"
    run_step "java-unit" "java/mvnw -f java/pom.xml -B test" \
        "$REPO_ROOT/java/mvnw" -f java/pom.xml -B -ntp test || true
    run_step "python-unit" "uv run --project agent pytest agent/tests/unit" \
        uv run --project agent --frozen pytest agent/tests/unit -q || true
    if [ -d "$REPO_ROOT/web/node_modules" ]; then
        run_step "web-test" "pnpm --dir web test" pnpm --dir web test || true
    else
        both "  -- web-test SKIPPED: web/node_modules missing"
        FAILURES+=("web-test-skipped")
    fi
fi

if [ "$SUITE" = "smoke" ] || [ "$SUITE" = "all-offline" ]; then
    head2 "smoke"

    run_step "infra-up" "docker compose -f infra/compose.yaml up -d" \
        docker compose -f "$REPO_ROOT/infra/compose.yaml" up -d || true

    run_step "package" "java/mvnw -f java/pom.xml -B -DskipTests package" \
        "$REPO_ROOT/java/mvnw" -f java/pom.xml -B -ntp -DskipTests package || true

    smoke_java_service() {
        local name="$1" jar="$2" port="$3"
        [ -f "$jar" ] || { echo "jar not found: $jar" >&2; return 1; }
        "$JAVA_HOME_21/bin/java" -jar "$jar" > "/tmp/smoke-$name.log" 2>&1 &
        local pid=$!
        http_up "http://127.0.0.1:$port/actuator/health" 90
        local result=$?
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
        return $result
    }

    for entry in \
        "gateway:java/gateway/target/gateway-0.1.0-SNAPSHOT.jar:8080" \
        "commerce-service:java/commerce-service/target/commerce-service-0.1.0-SNAPSHOT.jar:8081" \
        "fulfillment-service:java/fulfillment-service/target/fulfillment-service-0.1.0-SNAPSHOT.jar:8082" \
        "case-service:java/case-service/target/case-service-0.1.0-SNAPSHOT.jar:8083"; do
        name="${entry%%:*}"; rest="${entry#*:}"; jar="${rest%%:*}"; port="${rest##*:}"
        run_step "smoke-$name" "java -jar $jar  # then GET http://127.0.0.1:$port/actuator/health" \
            smoke_java_service "$name" "$REPO_ROOT/$jar" "$port" || true
    done

    smoke_agent_service() {
        uv run --project agent --frozen uvicorn resolveflow.api.app:app --port 8090 > /tmp/smoke-agent.log 2>&1 &
        local pid=$!
        http_up "http://127.0.0.1:8090/health" 60
        local result=$?
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
        return $result
    }
    run_step "smoke-agent-service" \
        "uv run --project agent uvicorn resolveflow.api.app:app --port 8090  # then GET :8090/health" \
        smoke_agent_service || true
fi

both ""
if [ "${#FAILURES[@]}" -gt 0 ]; then
    both "SUITE '$SUITE' FAILED: ${#FAILURES[@]} step(s)"
    for failure in "${FAILURES[@]}"; do both "  - $failure"; done
    printf '%s\n' "${TRANSCRIPT[@]}" > "$REPORT_PATH"
    both "report: $REPORT_PATH"
    exit 1
fi

both "SUITE '$SUITE' PASSED"
printf '%s\n' "${TRANSCRIPT[@]}" > "$REPORT_PATH"
both "report: $REPORT_PATH"
exit 0