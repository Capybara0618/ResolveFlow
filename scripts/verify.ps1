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
    doctor | format | unit | contracts | smoke | all-offline | system | faults |
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
    [string]$Case = '',
    # Which services the smoke suite starts. 'core' is the v1.2 default
    # (docs/core-scope.md:32, docs/architecture.md:43); 'compat' adds the assets kept
    # from the old protocol, which are not deployed by default.
    [ValidateSet('core', 'compat')]
    [string]$Profile = 'core'
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$reportDir = Join-Path $repoRoot 'reports/verify'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

# uv keeps its cache outside the repository by default. When that location is not
# writable (restricted sandbox, locked-down profile) every uv step dies before it
# reaches a test, which looks like a failing suite rather than a broken environment.
# Honour an explicit UV_CACHE_DIR, otherwise use one inside the repository.
if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = Join-Path $repoRoot 'tmp/uv-cache'
}
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null

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
    <#
      A service is up when it answers 200 *and* says UP. Both halves are required:
      an actuator health endpoint returns 200 with status DOWN when a dependency is
      unreachable, and treating that as healthy is the failure this guards against.

      PowerShell 7 returns .Content as a byte array for a response with no charset
      (Spring's actuator JSON is one), and -match on a byte array matches element
      wise and never finds a substring. Decode it first; PowerShell 5.1 already
      hands back a string, so both versions take the same path afterwards.
    #>
    param([string]$Url, [int]$TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            $body = if ($response.Content -is [byte[]]) {
                [Text.Encoding]::UTF8.GetString($response.Content)
            } else {
                [string]$response.Content
            }
            if ($response.StatusCode -eq 200 -and $body -match '"status"\s*:\s*"UP"') { return $true }
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
Write-Both "  profile : $Profile"
if ($Case) { Write-Both "  case  : $Case" }
Write-Both "  report: $reportPath"

$implementedSuites = @('doctor', 'format', 'unit', 'contracts', 'smoke', 'all-offline')

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

# --- contracts --------------------------------------------------------------
if ($Suite -in @('contracts', 'all-offline')) {
    <#
      The contract suite is where the two languages are made to agree. Java
      recomputes the frozen digests, signatures and enum values from
      contracts/fixtures; Python regenerates nothing and asserts that what is
      checked in still matches the corpus, so a fixture edited by hand to make a
      test pass is caught here instead of at the next service.
    #>
    Write-Header 'contracts'

    [void](Invoke-Step -Name 'python-contracts-freeze' -Command 'uv run --project agent python scripts/contracts_freeze.py --check' -Action {
            & uv run --project agent --frozen python scripts/contracts_freeze.py --check
        })
    [void](Invoke-Step -Name 'python-core-contracts-freeze' -Command 'uv run --project agent python scripts/contracts_core_freeze.py --check' -Action {
            & uv run --project agent --frozen python scripts/contracts_core_freeze.py --check
        })
    [void](Invoke-Step -Name 'python-contracts' -Command 'uv run --project agent pytest agent/tests/unit -k contracts' -Action {
            & uv run --project agent --frozen pytest agent/tests/unit -q -k 'contracts'
        })
    [void](Invoke-Step -Name 'java-contracts' -Command 'java\mvnw.cmd -f java/pom.xml -B -pl shared-kernel test' -Action {
            Invoke-JavaVersion -JavaHome $javaHome -MavenArgs @('-f', 'java/pom.xml', '-B', '-ntp', '-pl', 'shared-kernel', 'test')
        })
}

# --- smoke ------------------------------------------------------------------
if ($Suite -in @('smoke', 'all-offline')) {
    <#
      Smoke starts the packaged artifacts and reads their health endpoints. Unit
      tests already prove the context loads; this proves the jars that would be
      deployed actually boot and answer.
    #>
    Write-Header 'smoke'

    # The startable set comes from contracts/core/profile.json rather than a second list
    # here: two lists would drift, and the profile is the artefact the rest of the
    # project already reads. Nacos and Sentinel are 'not_required' there, so the
    # compat profile is the only one that starts the registry container.
    $coreProfile = Get-Content (Join-Path $repoRoot 'contracts/core/profile.json') -Raw | ConvertFrom-Json
    $javaServices = @($coreProfile.deployment.core_services | Where-Object { $_.language -eq 'java' } |
        ForEach-Object { $_.name })
    $compatServices = @($coreProfile.deployment.compat_only_services)
    if ($Profile -eq 'compat') { $javaServices += $compatServices }
    Write-Both "  services: $($javaServices -join ', '), agent" 'DarkGray'

    $composeArgs = @('compose', '-f', (Join-Path $repoRoot 'infra/compose.yaml'))
    if ($Profile -eq 'compat') { $composeArgs += @('--profile', 'compat') }
    $composeArgs += 'up'
    $composeArgs += '-d'

    [void](Invoke-Step -Name 'infra-up' -Command ("docker " + ($composeArgs -join ' ')) -Action {
            & docker @composeArgs
        })

    [void](Invoke-Step -Name 'package' -Command 'java\mvnw.cmd -f java/pom.xml -B -DskipTests package' -Action {
            Invoke-JavaVersion -JavaHome $javaHome -MavenArgs @('-f', 'java/pom.xml', '-B', '-ntp', '-DskipTests', 'package')
        })

    # Every startable service needs a launcher entry here; the set actually started is
    # the intersection with the profile, so adding a service to the profile without a
    # launcher fails the run instead of silently skipping it.
    $known = @(
        @{ Name = 'gateway';             Jar = 'java/gateway/target/gateway-0.1.0-SNAPSHOT.jar';                         Port = 8080 },
        @{ Name = 'commerce-service';    Jar = 'java/commerce-service/target/commerce-service-0.1.0-SNAPSHOT.jar';       Port = 8081 },
        @{ Name = 'fulfillment-service'; Jar = 'java/fulfillment-service/target/fulfillment-service-0.1.0-SNAPSHOT.jar'; Port = 8082 },
        @{ Name = 'case-service';        Jar = 'java/case-service/target/case-service-0.1.0-SNAPSHOT.jar';             Port = 8083 }
    )

    $unknown = @($javaServices | Where-Object { $_ -notin $known.Name })
    if ($unknown.Count -gt 0) {
        throw "profile lists startable service(s) with no launcher: $($unknown -join ', ')"
    }

    $services = @($known | Where-Object { $_.Name -in $javaServices })

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