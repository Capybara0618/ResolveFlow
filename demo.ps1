[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'status', 'verify')]
    [string]$Command = 'start',
    [switch]$SkipBuild,
    [switch]$NoBrowser,
    [switch]$Live
)

$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot 'agent/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "缺少项目 Python 环境：$python。请先按 README 完成一次依赖安装。"
}

$driverArgs = @('scripts/reviewer_demo.py')
if ($SkipBuild) {
    $driverArgs += '--skip-build'
}
$driverArgs += $Command
if ($Command -eq 'start' -and $NoBrowser) {
    $driverArgs += '--no-browser'
}
if ($Live -and $Command -ne 'start') {
    throw '-Live is supported only with start.'
}
$previousKey = $env:RESOLVEFLOW_MODEL_API_KEY
if ($Live) {
    $deepseekKey = [Environment]::GetEnvironmentVariable('Deepseek_API_KEY', 'User')
    if (-not $deepseekKey) { $deepseekKey = $env:Deepseek_API_KEY }
    if (-not $deepseekKey) { throw 'Missing Deepseek_API_KEY in the user environment.' }
    $env:RESOLVEFLOW_MODEL_API_KEY = $deepseekKey
    $driverArgs += '--live'
}

Push-Location $repoRoot
try {
    & $python @driverArgs
    $exitCode = $LASTEXITCODE
}
finally {
    $env:RESOLVEFLOW_MODEL_API_KEY = $previousKey
    Pop-Location
}
exit $exitCode
