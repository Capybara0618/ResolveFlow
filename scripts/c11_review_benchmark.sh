#!/usr/bin/env bash
# Linux/macOS equivalent of c11_review_benchmark.ps1; touches only c11_review_load.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SEED="${1:-42}"
TRIAL="${2:-full}"
[[ "$SEED" =~ ^[0-9]+$ ]] || { echo 'seed must be a nonnegative integer' >&2; exit 2; }
COMPOSE="$ROOT/infra/compose.yaml"
JAR="$ROOT/java/case-service/target/case-service-0.1.0-SNAPSHOT.jar"
REPORT="$ROOT/reports/c11-performance/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$REPORT"
LOG_DIR="$ROOT/tmp/c11-performance-debug/$(basename "$REPORT")"
mkdir -p "$LOG_DIR"
test -f "$JAR" || { echo "package Case before benchmarking: $JAR" >&2; exit 2; }

mysql_sql() {
    docker compose -f "$COMPOSE" exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' <<< "$1"
}
index_exists() {
    printf '%s\n' "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema='c11_review_load' AND table_name='aftersale_case' AND index_name='idx_case_review_queue';" |
        docker compose -f "$COMPOSE" exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -s'
}
PID=''
stop_case() {
    if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; PID=''; fi
}
trap stop_case EXIT
start_case() {
    local mode="$1" enabled='false'
    [ "$mode" = cache ] && enabled='true'
    CASE_DB_URL='jdbc:mysql://127.0.0.1:3306/c11_review_load?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false' \
    CASE_DB_USER=case_svc CASE_DB_PASSWORD=case_svc SERVER_PORT=18083 \
    REDIS_HOST=127.0.0.1 REDIS_PORT=56379 REVIEW_CACHE_ENABLED="$enabled" \
    RESOLVEFLOW_REVIEW_CACHE_NAMESPACE="rf:c11:load:$SEED" \
        java -jar "$JAR" >"$LOG_DIR/$mode-stdout.log" 2>"$LOG_DIR/$mode-stderr.log" &
    PID=$!
    for _ in $(seq 1 90); do
        if curl -fsS http://127.0.0.1:18083/actuator/health 2>/dev/null | grep -q '"status":"UP"'; then return; fi
        sleep 1
    done
    echo "isolated Case process did not become healthy; see $LOG_DIR/$mode-stderr.log" >&2
    exit 1
}

docker compose -f "$COMPOSE" up -d mysql redis
mysql_sql "CREATE DATABASE IF NOT EXISTS c11_review_load; GRANT ALL PRIVILEGES ON c11_review_load.* TO 'case_svc'@'%';"
start_case migrate
stop_case
sed -e '/^CREATE DATABASE IF NOT EXISTS c11_review_bench;/d' \
    -e '/^CREATE TABLE IF NOT EXISTS c11_review_bench.aftersale_case LIKE case_db.aftersale_case;/d' \
    -e 's/c11_review_bench/c11_review_load/g' -e 's/M-2002/M-1002/g' \
    "$ROOT/scripts/c11_review_queue_seed.sql" | docker compose -f "$COMPOSE" exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
if [ "$(index_exists)" = 1 ]; then
    mysql_sql 'ALTER TABLE c11_review_load.aftersale_case DROP INDEX idx_case_review_queue;'
fi
WARMUP=30 DURATION=60
if [ "$TRIAL" = trial ]; then WARMUP=2 DURATION=5; fi
for mode in baseline indexed cache; do
    if [ "$mode" = indexed ] && [ "$(index_exists)" = 0 ]; then
        mysql_sql 'ALTER TABLE c11_review_load.aftersale_case ADD INDEX idx_case_review_queue (merchant_id, status, updated_at DESC, case_id DESC);'
    fi
    start_case "$mode"
    python3 "$ROOT/scripts/c11_review_load.py" --mode "$mode" --seed "$SEED" \
        --warmup "$WARMUP" --duration "$DURATION" --repeats 2 --concurrency 10 30 \
        --output "$REPORT/$mode.json.gz"
    stop_case
done
python3 - "$REPORT" "$JAR" "$ROOT/scripts/c11_review_load.py" "$(docker info --format '{{.NCPU}}')" "$(docker info --format '{{.MemTotal}}')" <<'PY'
import hashlib, json, pathlib, sys
report, jar, script = map(pathlib.Path, sys.argv[1:4])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
(report / 'metadata.json').write_text(json.dumps({'jar_sha256': sha(jar), 'script_sha256': sha(script),
    'modes': ['baseline', 'indexed', 'cache'], 'rows': 20000, 'pending_review': 4000,
    'docker_cpus': int(sys.argv[4]), 'docker_mem_bytes': int(sys.argv[5])}, indent=2))
PY
echo "C11 performance raw data: $REPORT"
