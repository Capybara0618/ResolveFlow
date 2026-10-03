[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Command = 'start',
    [switch]$SkipBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'agent/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '缺少项目 Python 环境，请先按 README 安装依赖。'
}
if ($Command -ne 'start' -and ($SkipBuild -or $NoBrowser)) {
    throw '-SkipBuild 和 -NoBrowser 仅用于启动。'
}

$previousKey = $env:RESOLVEFLOW_MODEL_API_KEY
$driverArgs = @('scripts/project_runtime.py', $Command)
try {
    if ($Command -eq 'start') {
        $modelKey = $env:RESOLVEFLOW_MODEL_API_KEY
        if ([string]::IsNullOrWhiteSpace($modelKey)) { $modelKey = $env:Deepseek_API_KEY }
        if ([string]::IsNullOrWhiteSpace($modelKey)) {
            $modelKey = [Environment]::GetEnvironmentVariable('Deepseek_API_KEY', 'User')
        }
        if ([string]::IsNullOrWhiteSpace($modelKey)) {
            throw '缺少 Deepseek_API_KEY。请配置用户环境变量后再启动，项目不会降级为只读模式。'
        }
        $env:RESOLVEFLOW_MODEL_API_KEY = $modelKey.Trim()
        if ($SkipBuild) { $driverArgs += '--skip-build' }
        if ($NoBrowser) { $driverArgs += '--no-browser' }
    }
    Push-Location $repoRoot
    try {
        & $python @driverArgs
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
}
finally {
    $env:RESOLVEFLOW_MODEL_API_KEY = $previousKey
}
exit $exitCode
