<#
.SYNOPSIS
    Verification entry point for ResolveFlow.

.DESCRIPTION
    Command contract from docs/engineering.md 2. Prints every command it runs and
    the report path it writes, so a passing suite leaves evidence rather than a
    bare exit code.

    Suites that belong to a later task are reported as NOT IMPLEMENTED and exit
    non-zero when requested directly. A suite must never look like it passed
    because it silently ran nothing (docs/engineering.md 5).

    A script must not skip failing tests and still return 0.

.PARAMETER Suite
    doctor | format | unit | smoke | all-offline | contracts | system | faults |
    performance | agent-eval | rag-eval | harness | harness-eval

.PARAMETER Mode
    mock | live. Live modes consume paid model API quota and stay unimplemented
    until T31/T39.

.PARAMETER Seed
    Seed for fault and performance suites (T29/T30).

.PARAMETER Case
    Filter to a single fault or test case.

.EXAMPLE
    pwsh -File scripts/verify.ps1 -Suite all-offline
#>
[CmdletBinding()]
param(
    [string]$Suite = 'all-offline',
    [string]$Mode = 'mock',
    [int]$Seed = 42,
    [string]$Case = ''
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$reportDir = Join-Path $repoRoot 'reports/verify'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$reportPath = Join-Path $reportDir "$stamp-$Suite.txt"
$script:Transcript = New-Object System.Collections.Generic.List[string]
$script:Failures = @()

function Write-Both([string]$Message, [string]$Color = 'Gray') {
    Write-Host $Message -ForegroundColor $Color
    $script:Transcript.Add($Message)
}

function Write-Header([string]$Title) { Write-Both '' ; Write-Both "== $Title" 'Cyan' }

function Resolve-JavaHome {
    foreach ($root in @((Join-Path $HOME '.jdks'), 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Java',
            $env:JAVA_HOME)) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        foreach ($dir in (Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue)) {
            $javaExe = Join-Path $dir.FullName 'bin/java.exe'
            if (-not (Test-Path $javaExe)) { continue }
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            $raw = & $javaExe '-version' 2>&1 | Out-String
            $ErrorActionPreference = $previous
            if ($raw -match 'version "(\d+)' -and [int]$Matches[1] -ge 21) { return $dir.FullName }
        }
    }
    return $null
}

function Invoke-Step {
    <#
      Runs one verification step. Records the exact command so the report shows
      what actually ran, not a summary of intent.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Both "  -- $Name"
    Write-Both "     \$ $Command" 'DarkGray'

    $started = Get-Date
    try {
        & $Action
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
    } catch {
        $exitCode = 1
        Write-Both "     exception: $($_.Exception.Message)" 'Red'
    }
    $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

    if ($exitCode -eq 0) {
        Write-Both "     PASS (${elapsed}s)" 'Green'
        return $true
    }

    Write-Both "     FAIL (exit $exitCode, ${elapsed}s)" 'Red'
    $script:Failures += $Name
    return $false
}

function Invoke-JavaVersion {
    param([string]$JavaHome, [string[]]$MavenArgs)
    $mvnw = Join-Path $repoRoot 'java/mvnw.cmd'
    $env:JAVA_HOME = $JavaHome
    & $mvnw @MavenArgs
}

function Test-HttpUp {
    param([string]$Url, [int]$TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200 -and $response.Content -match 'UP') { return $true }
        } catch { Start-Sleep -Milliseconds 1500 }
    }
    return $false
}

# --- Suite definitions ------------------------------------------------------
$javaHome = Resolve-JavaHome
if (-not $javaHome) {
    Write-Host 'JDK 21 not found; run scripts/doctor.ps1 for detail.' -ForegroundColor Red
    exit 1
}
$env:JAVA_HOME = $javaHome

# Owned by a later task; must be explicit rather than silently empty.
$notImplemented = @{
    'contracts'    = 'T02 契约固化与跨语言fixture'
    'system'       = 'T14 case执行编排与退款闭环'
    'faults'       = 'T29 故障实验完整矩阵'
    'performance'  = 'T30 性能与RAG对照'
    'rag-eval'     = 'T30 性能与RAG对照'
    'agent-eval'   = 'T24/T31 基线与live评测'
    'harness'      = 'T38 隔离回放与GH验收'
    'harness-eval' = 'T39 Harness消融'
}

Write-Both "ResolveFlow verify" 'White'
Write-Both "  suite : $Suite"
Write-Both "  mode  : $Mode"
Write-Both "  seed  : $Seed"
if ($Case) { Write-Both "  case  : $Case" }
Write-Both "  report: $reportPath"

$implementedSuites = @('doctor', 'format', 'unit', 'smoke', 'all-offline')

# An unrecognised suite must fail loudly: otherwise a typo would run zero steps
# and still report PASSED, which is the "skip masquerading as pass" failure
# docs/engineering.md 5 forbids.
if ($implementedSuites -notcontains $Suite -and -not $notImplemented.ContainsKey($Suite)) {
    Write-Both ''
    Write-Both "UNKNOWN SUITE: '$Suite' is not a suite this script implements." 'Red'
    Write-Both "Known suites: $($implementedSuites -join ' ')" 'Red'
    Write-Both "Deferred to a later task: $(($notImplemented.Keys | Sort-Object) -join ' ')" 'Red'
    Write-Both 'Refusing to report success for a suite that ran nothing.' 'Red'
    $script:Transcript | Set-Content -Path $reportPath -Encoding UTF8
    exit 64
}

if ($notImplemented.ContainsKey($Suite)) {
    Write-Both ''
    Write-Both "NOT IMPLEMENTED: suite '$Suite' belongs to $($notImplemented[$Suite])." 'Yellow'
    Write-Both 'Refusing to report success for a suite that ran nothing.' 'Yellow'
    $script:Transcript | Set-Content -Path $reportPath -Encoding UTF8
    exit 2
}

# --- doctor -----------------------------------------------------------------
if ($Suite -eq 'doctor') {
    Write-Header 'doctor'
    [void](Invoke-Step -Name 'doctor' -Command 'pwsh -File scripts/doctor.ps1' -Action {
            & (Join-Path $PSScriptRoot 'doctor.ps1')
        })
}

# --- format -----------------------------------------------------------------
if ($Suite -in @('format', 'all-offline')) {
    Write-Header 'format'
    [void](Invoke-Step -Name 'java-spotless' -Command 'java\mvnw.cmd -f java/pom.xml -B spotless:check' -Action {
            Invoke-JavaVersion -JavaHome $javaHome -MavenArgs @('-f', 'java/pom.xml', '-B', '-ntp', 'spotless:check')
        })
    [void](Invoke-Step -Name 'python-ruff' -Command 'uv run --project agent ruff check agent/src agent/tests' -Action {
            & uv run --project agent --frozen ruff check agent/src agent/tests
        })
    [void](Invoke-Step -Name 'python-mypy' -Command 'uv run --project agent mypy agent/src' -Action {
            & uv run --project agent --frozen mypy agent/src
        })
    if (Test-Path (Join-Path $repoRoot 'web/node_modules')) {
        [void](Invoke-Step -Name 'web-typecheck' -Command 'pnpm --dir web typecheck' -Action {
                & pnpm --dir web typecheck
            })
    } else {
        Write-Both '  -- web-typecheck SKIPPED: web/node_modules missing (run pnpm --dir web install)' 'Yellow'
        $script:Failures += 'web-typecheck-skipped'
    }
}

# --- unit -------------------------------------------------------------------
if ($Suite -in @('unit', 'all-offline')) {
    Write-Header 'unit'
    [void](Invoke-Step -Name 'java-unit' -Command 'java\mvnw.cmd -f java/pom.xml -B test' -Action {
            Invoke-JavaVersion -JavaHome $javaHome -MavenArgs @('-f', 'java/pom.xml', '-B', '-ntp', 'test')
        })
    [void](Invoke-Step -Name 'python-unit' -Command 'uv run --project agent pytest agent/tests/unit' -Action {
            & uv run --project agent --frozen pytest agent/tests/unit -q
        })
    if (Test-Path (Join-Path $repoRoot 'web/node_modules')) {
        [void](Invoke-Step -Name 'web-test' -Command 'pnpm --dir web test' -Action { & pnpm --dir web test })
    } else {
        Write-Both '  -- web-test SKIPPED: web/node_modules missing' 'Yellow'
        $script:Failures += 'web-test-skipped'
    }
}

# --- smoke ------------------------------------------------------------------
if ($Suite -in @('smoke', 'all-offline')) {
    <#
      Smoke starts the packaged artifacts and reads their health endpoints. Unit
      tests already prove the context loads; this proves the jars that would be
      deployed actually boot and answer.
    #>
    Write-Header 'smoke'

    [void](Invoke-Step -Name 'infra-up' -Command 'docker compose -f infra/compose.yaml up -d' -Action {
            & docker compose -f (Join-Path $repoRoot 'infra/compose.yaml') up -d
        })

    [void](Invoke-Step -Name 'package' -Command 'java\mvnw.cmd -f java/pom.xml -B -DskipTests package' -Action {
            Invoke-JavaVersion -JavaHome $javaHome -MavenArgs @('-f', 'java/pom.xml', '-B', '-ntp', '-DskipTests', 'package')
        })

    $services = @(
        @{ Name = 'gateway';             Jar = 'java/gateway/target/gateway-0.1.0-SNAPSHOT.jar';                         Port = 8080 },
        @{ Name = 'commerce-service';    Jar = 'java/commerce-service/target/commerce-service-0.1.0-SNAPSHOT.jar';       Port = 8081 },
        @{ Name = 'fulfillment-service'; Jar = 'java/fulfillment-service/target/fulfillment-service-0.1.0-SNAPSHOT.jar'; Port = 8082 },
        @{ Name = 'case-service';        Jar = 'java/case-service/target/case-service-0.1.0-SNAPSHOT.jar';             Port = 8083 }
    )

    foreach ($service in $services) {
        $jarPath = Join-Path $repoRoot $service.Jar
        $healthUrl = "http://127.0.0.1:$($service.Port)/actuator/health"

        [void](Invoke-Step -Name "smoke-$($service.Name)" -Command "java -jar $($service.Jar)  # then GET $healthUrl" -Action {
                if (-not (Test-Path $jarPath)) { throw "jar not found: $jarPath" }
                $process = Start-Process -FilePath (Join-Path $javaHome 'bin/java.exe') `
                    -ArgumentList @('-jar', $jarPath) -PassThru -WindowStyle Hidden
                try {
                    if (-not (Test-HttpUp -Url $healthUrl -TimeoutSeconds 90)) {
                        throw "health endpoint did not report UP at $healthUrl"
                    }
                } finally {
                    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
                }
            })
    }

    # The Agent process is Python; same contract, different launcher.
    [void](Invoke-Step -Name 'smoke-agent-service' -Command 'uv run --project agent uvicorn resolveflow.api.app:app --port 8090  # then GET http://127.0.0.1:8090/health' -Action {
            $process = Start-Process -FilePath 'uv' `
                -ArgumentList @('run', '--project', 'agent', '--frozen', 'uvicorn', 'resolveflow.api.app:app', '--port', '8090') `
                -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden
            try {
                if (-not (Test-HttpUp -Url 'http://127.0.0.1:8090/health' -TimeoutSeconds 60)) {
                    throw 'agent health endpoint did not report UP'
                }
            } finally {
                if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
            }
        })
}

# --- Summary ----------------------------------------------------------------
Write-Both ''
if ($script:Failures.Count -gt 0) {
    Write-Both "SUITE '$Suite' FAILED: $($script:Failures.Count) step(s)" 'Red'
    foreach ($failure in $script:Failures) { Write-Both "  - $failure" 'Red' }
    $script:Transcript | Set-Content -Path $reportPath -Encoding UTF8
    Write-Both "report: $reportPath"
    exit 1
}

Write-Both "SUITE '$Suite' PASSED" 'Green'
$script:Transcript | Set-Content -Path $reportPath -Encoding UTF8
Write-Both "report: $reportPath"
exit 0