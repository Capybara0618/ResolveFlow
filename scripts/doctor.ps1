<#
.SYNOPSIS
    Environment check for ResolveFlow.

.DESCRIPTION
    Reports the toolchain, memory, ports and running infrastructure images.
    Prints actionable detail for anything missing and exits non-zero when a
    required tool is absent, so a downstream command fails here rather than
    three steps later with a confusing message.

    This script never stops or kills anything. Port conflicts are reported for a
    human to resolve (docs/engineering.md 4).

    Runs on Windows PowerShell 5.1 as well as PowerShell 7.

.EXAMPLE
    pwsh -File scripts/doctor.ps1
#>
[CmdletBinding()]
param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$script:Failures = @()
$script:Warnings = @()

function Write-Section([string]$Title) {
    if (-not $Quiet) {
        Write-Host ''
        Write-Host "== $Title" -ForegroundColor Cyan
    }
}

function Write-Ok([string]$Message) { if (-not $Quiet) { Write-Host "  [ ok ] $Message" -ForegroundColor Green } }
function Write-Info([string]$Message) { if (-not $Quiet) { Write-Host "  $Message" -ForegroundColor DarkGray } }

function Add-Warning([string]$Message) {
    $script:Warnings += $Message
    Write-Host "  [warn] $Message" -ForegroundColor Yellow
}

function Add-Failure([string]$Message) {
    $script:Failures += $Message
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

function Invoke-Native {
    <#
      Captures stdout+stderr from an external command without letting
      $ErrorActionPreference='Stop' turn a tool's stderr banner into a
      terminating error. java -version and docker both write to stderr.
    #>
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @()
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Exe @Arguments 2>&1 | Out-String
        return $output.Trim()
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Get-JavaMajor([string]$JavaExe) {
    $raw = Invoke-Native -Exe $JavaExe -Arguments @('-version')
    if ($raw -and $raw -match 'version "(\d+)') { return [int]$Matches[1] }
    return $null
}

function Resolve-JavaHome21 {
    <#
      The host default JDK may be older than 21 (docs/compatibility-report.md 2),
      so resolve explicitly rather than trusting JAVA_HOME or `java` on PATH.
    #>
    $candidates = @()
    if ($env:JAVA_HOME) { $candidates += $env:JAVA_HOME }

    foreach ($root in @((Join-Path $HOME '.jdks'), 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Java')) {
        if (Test-Path $root) {
            $candidates += (Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                Select-Object -ExpandProperty FullName)
        }
    }

    foreach ($candidate in $candidates) {
        $javaExe = Join-Path $candidate 'bin/java.exe'
        if (-not (Test-Path $javaExe)) { continue }
        $major = Get-JavaMajor $javaExe
        if ($major -ne $null -and $major -ge 21) { return $candidate }
    }
    return $null
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Write-Host 'ResolveFlow doctor' -ForegroundColor White
Write-Info "repo root: $repoRoot"

# --- Java -------------------------------------------------------------------
Write-Section 'Java'
$javaHome = Resolve-JavaHome21
if ($javaHome) {
    Write-Ok "JDK 21 at $javaHome"

    # Surface the trap explicitly: builds fail confusingly if PATH java is older.
    $pathJava = Get-Command java -ErrorAction SilentlyContinue
    if ($pathJava) {
        $pathMajor = Get-JavaMajor 'java'
        if ($pathMajor -ne $null -and $pathMajor -lt 21) {
            Add-Warning ("java on PATH is $pathMajor, not 21. Set JAVA_HOME=$javaHome before running Maven; " +
                'the enforcer plugin will otherwise fail the build.')
        }
    }
} else {
    $configured = if ($env:JAVA_HOME) { $env:JAVA_HOME } else { '(unset)' }
    Add-Failure "JDK 21 not found. JAVA_HOME is $configured. Install one under ~/.jdks or set JAVA_HOME to a JDK 21 install."
}

# --- Maven wrapper ----------------------------------------------------------
Write-Section 'Maven'
$mvnwCmd = Join-Path $repoRoot 'java/mvnw.cmd'
if (Test-Path $mvnwCmd) {
    Write-Ok 'java/mvnw.cmd present (wrapper pins Maven 3.9.16)'
} else {
    Add-Failure 'java/mvnw.cmd missing; regenerate the wrapper before building'
}

# --- Python -----------------------------------------------------------------
Write-Section 'Python'
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Ok (Invoke-Native -Exe 'uv' -Arguments @('--version'))
    $pythonExe = Join-Path $repoRoot 'agent/.venv/Scripts/python.exe'
    if (Test-Path $pythonExe) {
        Write-Ok "agent venv: $(Invoke-Native -Exe $pythonExe -Arguments @('--version'))"
    } else {
        Add-Warning 'agent/.venv missing; run: uv sync --project agent --frozen --all-extras'
    }
} else {
    Add-Failure 'uv not found on PATH; the Agent project is managed by uv'
}

# --- Node / pnpm ------------------------------------------------------------
Write-Section 'Node'
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVersion = Invoke-Native -Exe 'node' -Arguments @('--version')
    Write-Ok "node $nodeVersion"
    if ($nodeVersion -and $nodeVersion -notmatch 'v22\.') {
        Add-Warning "web/ declares engines node >=22 <23; current is $nodeVersion"
    }
} else {
    Add-Warning 'node not found; the web build and tests will not run'
}

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    Write-Ok ("pnpm " + (Invoke-Native -Exe 'pnpm' -Arguments @('--version')))
} else {
    Add-Warning 'pnpm not found; run: npm install -g pnpm'
}

# --- Docker -----------------------------------------------------------------
Write-Section 'Docker'
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    $serverVersion = Invoke-Native -Exe 'docker' -Arguments @('version', '--format', '{{.Server.Version}}')
    if ($serverVersion -and $serverVersion -match '^\d') {
        Write-Ok "docker server $serverVersion"
    } else {
        Add-Failure 'Docker daemon not reachable. Start Docker Desktop; a stopped daemon is not a code problem.'
    }
} else {
    Add-Failure 'docker not found; the infrastructure stack cannot start'
}

# --- Memory -----------------------------------------------------------------
Write-Section 'Memory'
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    $memoryMessage = "RAM total $totalGb GB, free $freeGb GB"
    # docs/architecture.md 6: 16 GB is the comfortable development baseline.
    if ($totalGb -lt 16) { Add-Warning "$memoryMessage (16 GB recommended for the full stack)" }
    else { Write-Ok $memoryMessage }
} catch {
    Add-Warning 'could not read memory information'
}

# --- Ports ------------------------------------------------------------------
Write-Section 'Ports'
$portMap = @(
    @{ Port = 3306;  Name = 'mysql' },
    @{ Port = 55432; Name = 'postgres' },
    @{ Port = 56379; Name = 'redis' },
    @{ Port = 9876;  Name = 'rocketmq-namesrv' },
    @{ Port = 10911; Name = 'rocketmq-broker' },
    @{ Port = 8848;  Name = 'nacos' },
    @{ Port = 8080;  Name = 'gateway' },
    @{ Port = 8081;  Name = 'commerce-service' },
    @{ Port = 8082;  Name = 'fulfillment-service' },
    @{ Port = 8083;  Name = 'case-service' },
    @{ Port = 8090;  Name = 'agent-service' }
)

foreach ($entry in $portMap) {
    $listening = $null
    try { $listening = Get-NetTCPConnection -State Listen -LocalPort $entry.Port -ErrorAction SilentlyContinue } catch { }

    if ($listening) {
        # Occupied is informational: it may be this project's own stack, or another
        # project's. Never kill it; report the owning pid for a human to judge.
        $ownerPids = ($listening | Select-Object -ExpandProperty OwningProcess -Unique) -join ','
        Write-Info ("port {0,-6} {1,-20} in use (pid {2})" -f $entry.Port, $entry.Name, $ownerPids)
    } else {
        Write-Info ("port {0,-6} {1,-20} free" -f $entry.Port, $entry.Name)
    }
}

# --- Infrastructure ---------------------------------------------------------
Write-Section 'Infrastructure'
if ($docker) {
    $composeFile = Join-Path $repoRoot 'infra/compose.yaml'
    $composePs = Invoke-Native -Exe 'docker' -Arguments @('compose', '-f', $composeFile, 'ps', '--format', '{{.Service}}|{{.Status}}')
    if ($composePs -and $composePs -match '\|') {
        foreach ($line in ($composePs -split "`n")) {
            if ($line -match '\|') {
                $parts = $line -split '\|'
                Write-Info ("{0,-18} {1}" -f $parts[0].Trim(), $parts[1].Trim())
            }
        }
    } else {
        Write-Info 'stack not started: docker compose -f infra/compose.yaml up -d'
    }
}

# --- Summary ----------------------------------------------------------------
Write-Host ''
if ($script:Failures.Count -gt 0) {
    Write-Host ("FAILED: {0} required item(s) missing, {1} warning(s)" -f $script:Failures.Count, $script:Warnings.Count) -ForegroundColor Red
    foreach ($failure in $script:Failures) { Write-Host "  - $failure" -ForegroundColor Red }
    exit 1
}

if ($script:Warnings.Count -gt 0) {
    Write-Host ("OK with {0} warning(s)" -f $script:Warnings.Count) -ForegroundColor Yellow
    exit 0
}

Write-Host 'OK: environment looks ready' -ForegroundColor Green
exit 0