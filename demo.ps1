[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'status', 'verify')]
    [string]$Command = 'start',
    [switch]$SkipBuild,
    [switch]$NoBrowser
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

Push-Location $repoRoot
try {
    & $python @driverArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitCode
