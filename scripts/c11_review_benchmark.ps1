<#
  C11.2e/C12 isolated review-queue comparison. Never alters case_db or shared
  Redis keys. -Trial shortens windows; default follows docs/evaluation.md §6.
#>
[CmdletBinding()]
param(
    [int]$Seed = 42,
    [switch]$Trial
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compose = Join-Path $root 'infra/compose.yaml'
$jar = Join-Path $root 'java/case-service/target/case-service-0.1.0-SNAPSHOT.jar'
$report = Join-Path $root ('reports/c11-performance/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $report | Out-Null
$logDir = Join-Path $root ('tmp/c11-performance-debug/' + (Split-Path $report -Leaf))
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Invoke-Mysql([string]$Sql) {
    $Sql | docker compose -f $compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
    if ($LASTEXITCODE -ne 0) { throw "isolated MySQL command failed ($LASTEXITCODE)" }
}

function Index-Exists {
    $sql = "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema='c11_review_load' AND table_name='aftersale_case' AND index_name='idx_case_review_queue';"
    $answer = $sql | docker compose -f $compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -s'
    if ($LASTEXITCODE -ne 0) { throw 'index inspection failed' }
    return [int]($answer | Select-Object -Last 1)
}

function Wait-Health {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:18083/actuator/health' -TimeoutSec 2
            if ($health.status -eq 'UP') { return }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    throw 'isolated Case process did not become healthy on port 18083'
}

function Start-Case([string]$Mode) {
    $env:CASE_DB_URL = 'jdbc:mysql://127.0.0.1:3306/c11_review_load?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false'
    $env:CASE_DB_USER = 'case_svc'
    $env:CASE_DB_PASSWORD = 'case_svc'
    $env:SERVER_PORT = '18083'
    $env:REDIS_HOST = '127.0.0.1'
    $env:REDIS_PORT = '56379'
    $env:REVIEW_CACHE_ENABLED = if ($Mode -eq 'cache') { 'true' } else { 'false' }
    $env:RESOLVEFLOW_REVIEW_CACHE_NAMESPACE = "rf:c11:load:$Seed"
    $out = Join-Path $logDir "$Mode-stdout.log"
    $err = Join-Path $logDir "$Mode-stderr.log"
    $process = Start-Process -FilePath (Join-Path $env:JAVA_HOME 'bin/java.exe') `
        -ArgumentList @('-jar', $jar) -WorkingDirectory $root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err
    try { Wait-Health; return $process } catch {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        throw
    }
}

function Stop-Case($Process) {
    if ($Process -and -not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
}

if (-not (Test-Path $jar)) { throw "package Case before benchmarking: $jar" }
if (-not $env:JAVA_HOME) { throw 'JAVA_HOME must point to JDK 21' }
docker compose -f $compose up -d mysql redis
if ($LASTEXITCODE -ne 0) { throw 'MySQL/Redis startup failed' }
Invoke-Mysql "CREATE DATABASE IF NOT EXISTS c11_review_load; GRANT ALL PRIVILEGES ON c11_review_load.* TO 'case_svc'@'%';"

$caseProcess = $null
try {
    # Flyway migrates only the isolated schema. Existing user schemas are untouched.
    $caseProcess = Start-Case 'migrate'
    Stop-Case $caseProcess
    $caseProcess = $null
    $seedSql = Get-Content (Join-Path $root 'scripts/c11_review_queue_seed.sql') -Raw -Encoding UTF8
    $seedSql = $seedSql -replace '(?m)^CREATE DATABASE IF NOT EXISTS c11_review_bench;\r?\n', ''
    $seedSql = $seedSql -replace '(?m)^CREATE TABLE IF NOT EXISTS c11_review_bench.aftersale_case LIKE case_db.aftersale_case;\r?\n', ''
    $seedSql = $seedSql.Replace('c11_review_bench', 'c11_review_load').Replace('M-2002', 'M-1002')
    Invoke-Mysql $seedSql

    if (Index-Exists) { Invoke-Mysql 'ALTER TABLE c11_review_load.aftersale_case DROP INDEX idx_case_review_queue;' }
    foreach ($mode in @('baseline', 'indexed', 'cache')) {
        if ($mode -eq 'indexed') {
            if (-not (Index-Exists)) {
                Invoke-Mysql 'ALTER TABLE c11_review_load.aftersale_case ADD INDEX idx_case_review_queue (merchant_id, status, updated_at DESC, case_id DESC);'
            }
        }
        $caseProcess = Start-Case $mode
        $warmup = if ($Trial) { 2 } else { 30 }
        $duration = if ($Trial) { 5 } else { 60 }
        $raw = Join-Path $report "$mode.json.gz"
        & python (Join-Path $root 'scripts/c11_review_load.py') --mode $mode --seed $Seed `
            --warmup $warmup --duration $duration --repeats 2 --concurrency 10 30 --output $raw
        if ($LASTEXITCODE -ne 0) { throw "$mode HTTP benchmark failed" }
        Stop-Case $caseProcess
        $caseProcess = $null
    }
    $metadata = [ordered]@{
        seed = $Seed
        trial = [bool]$Trial
        rows = 20000
        pending_review = 4000
        jar_sha256 = (Get-FileHash $jar -Algorithm SHA256).Hash
        script_sha256 = (Get-FileHash (Join-Path $root 'scripts/c11_review_load.py') -Algorithm SHA256).Hash
        compose_sha256 = (Get-FileHash $compose -Algorithm SHA256).Hash
        docker_cpus = [int](docker info --format '{{.NCPU}}')
        docker_mem_bytes = [long](docker info --format '{{.MemTotal}}')
        modes = @('baseline', 'indexed', 'cache')
    }
    $metadata | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $report 'metadata.json') -Encoding UTF8
    Write-Host "C11 performance raw data: $report"
} finally {
    Stop-Case $caseProcess
}
