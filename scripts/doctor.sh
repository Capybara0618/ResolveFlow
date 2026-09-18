#!/usr/bin/env bash
# Linux/macOS equivalent of scripts/doctor.ps1 — the entry point CI and non-Windows
# developers use. Behaviour must stay in step with the PowerShell version: same
# checks, same exit semantics (non-zero when a required tool is missing).
#
# Never stops or kills anything; port conflicts are reported, not resolved.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUIET="${QUIET:-0}"

FAILURES=()
WARNINGS=()

section() { [ "$QUIET" = "1" ] || { echo; echo "== $1"; }; }
ok()      { [ "$QUIET" = "1" ] || echo "  [ ok ] $1"; }
info()    { [ "$QUIET" = "1" ] || echo "  $1"; }
warn()    { WARNINGS+=("$1"); echo "  [warn] $1"; }
fail()    { FAILURES+=("$1"); echo "  [FAIL] $1"; }

echo "ResolveFlow doctor"
info "repo root: $REPO_ROOT"

# --- Java -------------------------------------------------------------------
section "Java"
JAVA_HOME_21=""
java_major() {
    # java -version prints to stderr; capture both streams.
    "$1" -version 2>&1 | head -1 | sed -n 's/.*version "\([0-9]*\).*/\1/p'
}

for candidate in "${JAVA_HOME:-}" "$HOME/.jdks"/* /usr/lib/jvm/* /opt/java/*; do
    [ -n "$candidate" ] || continue
    [ -x "$candidate/bin/java" ] || continue
    major="$(java_major "$candidate/bin/java")"
    if [ -n "$major" ] && [ "$major" -ge 21 ]; then
        JAVA_HOME_21="$candidate"
        break
    fi
done

if [ -n "$JAVA_HOME_21" ]; then
    ok "JDK 21 at $JAVA_HOME_21"
    if command -v java >/dev/null 2>&1; then
        path_major="$(java_major java)"
        if [ -n "$path_major" ] && [ "$path_major" -lt 21 ]; then
            warn "java on PATH is $path_major, not 21. Set JAVA_HOME=$JAVA_HOME_21 before running Maven."
        fi
    fi
else
    fail "JDK 21 not found (JAVA_HOME=${JAVA_HOME:-unset}). Builds will fail on the enforcer rule."
fi

# --- Maven wrapper ----------------------------------------------------------
section "Maven"
if [ -f "$REPO_ROOT/java/mvnw" ]; then
    ok "java/mvnw present (wrapper pins Maven 3.9.16)"
else
    fail "java/mvnw missing; regenerate the wrapper before building"
fi

# --- Python -----------------------------------------------------------------
section "Python"
if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version 2>&1)"
    if [ -x "$REPO_ROOT/agent/.venv/bin/python" ]; then
        ok "agent venv: $("$REPO_ROOT/agent/.venv/bin/python" --version 2>&1)"
    else
        warn "agent/.venv missing; run: uv sync --project agent --frozen --all-extras"
    fi
else
    fail "uv not found on PATH; the Agent project is managed by uv"
fi

# --- Node / pnpm ------------------------------------------------------------
section "Node"
if command -v node >/dev/null 2>&1; then
    node_version="$(node --version)"
    ok "node $node_version"
    case "$node_version" in
        v22.*) ;;
        *) warn "web/ declares engines node >=22 <23; current is $node_version" ;;
    esac
else
    warn "node not found; the web build and tests will not run"
fi

if command -v pnpm >/dev/null 2>&1; then
    ok "pnpm $(pnpm --version 2>&1)"
else
    warn "pnpm not found; run: npm install -g pnpm"
fi

# --- Docker -----------------------------------------------------------------
section "Docker"
if command -v docker >/dev/null 2>&1; then
    server_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
    if [ -n "$server_version" ]; then
        ok "docker server $server_version"
    else
        fail "Docker daemon not reachable. Start it; a stopped daemon is not a code problem."
    fi
else
    fail "docker not found; the infrastructure stack cannot start"
fi

# --- Memory -----------------------------------------------------------------
section "Memory"
if [ -r /proc/meminfo ]; then
    total_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
    avail_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
    total_gb=$((total_kb / 1024 / 1024))
    avail_gb=$((avail_kb / 1024 / 1024))
    if [ "$total_gb" -lt 16 ]; then
        warn "RAM total ${total_gb} GB, available ${avail_gb} GB (16 GB recommended for the full stack)"
    else
        ok "RAM total ${total_gb} GB, available ${avail_gb} GB"
    fi
else
    info "memory information unavailable on this platform"
fi

# --- Ports ------------------------------------------------------------------
section "Ports"

# Returns 0 when something is listening on the port. Prefers ss/lsof, then falls
# back to a TCP connect via bash's /dev/tcp — git bash on Windows has neither ss
# nor lsof, and reporting "free" there would be a dangerous false negative.
port_in_use() {
    local port="$1"

    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -q ":${port} " && return 0
        return 1
    fi

    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1 && return 0
        return 1
    fi

    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3>&- 3<&- 2>/dev/null
        return 0
    fi
    return 1
}

# name:port pairs; keep in step with infra/compose.yaml and docs/architecture.md.
for entry in \
    mysql:3306 postgres:55432 redis:56379 \
    rocketmq-namesrv:9876 rocketmq-broker:10911 nacos:8848 \
    gateway:8080 commerce-service:8081 fulfillment-service:8082 case-service:8083 agent-service:8090; do
    name="${entry%%:*}"
    port="${entry##*:}"
    if port_in_use "$port"; then
        info "port ${port} ${name} in use"
    else
        info "port ${port} ${name} free"
    fi
done

# --- Infrastructure ---------------------------------------------------------
section "Infrastructure"
if command -v docker >/dev/null 2>&1 && [ -f "$REPO_ROOT/infra/compose.yaml" ]; then
    if compose_ps="$(docker compose -f "$REPO_ROOT/infra/compose.yaml" ps --format '{{.Service}}|{{.Status}}' 2>/dev/null)" \
        && [ -n "$compose_ps" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] && info "${line//|/  }"
        done <<< "$compose_ps"
    else
        info "stack not started: docker compose -f infra/compose.yaml up -d"
    fi
fi

# --- Summary ----------------------------------------------------------------
echo
if [ "${#FAILURES[@]}" -gt 0 ]; then
    echo "FAILED: ${#FAILURES[@]} required item(s) missing, ${#WARNINGS[@]} warning(s)"
    for failure in "${FAILURES[@]}"; do echo "  - $failure"; done
    exit 1
fi

if [ "${#WARNINGS[@]}" -gt 0 ]; then
    echo "OK with ${#WARNINGS[@]} warning(s)"
    exit 0
fi

echo "OK: environment looks ready"
exit 0