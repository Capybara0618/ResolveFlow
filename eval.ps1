[CmdletBinding()]
param(
    [ValidateSet('validate', 'rag', 'mock', 'live', 'harness', 'replay', 'report', 'compare', 'rescore', 'review-template', 'review-score')]
    [string]$Mode = 'validate',
    [ValidateSet('all', 'dev', 'test')]
    [string]$Split = 'all',
    [string[]]$Case = @(),
    [string]$Output,
    [string]$LiveBudget,
    [string]$InputReport,
    [string]$Baseline,
    [switch]$Bm25Only,
    [string]$Review
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot 'agent/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '缺少 agent/.venv，请先按项目运行说明安装锁定依赖。'
}
$taskArgs = @('scripts/agent_eval.py', $Mode, '--split', $Split)
foreach ($caseId in $Case) { $taskArgs += @('--case', $caseId) }
if ($Output) { $taskArgs += @('--output', $Output) }
if ($LiveBudget) { $taskArgs += @('--live-budget', $LiveBudget) }
if ($InputReport) { $taskArgs += @('--input-report', $InputReport) }
if ($Baseline) { $taskArgs += @('--baseline', $Baseline) }
if ($Bm25Only) { $taskArgs += '--bm25-only' }
if ($Review) { $taskArgs += @('--review', $Review) }
$previousKey = $env:RESOLVEFLOW_MODEL_API_KEY
try {
    if ($Mode -eq 'live') {
        $taskKey = $env:RESOLVEFLOW_MODEL_API_KEY
        if ([string]::IsNullOrWhiteSpace($taskKey)) { $taskKey = $env:Deepseek_API_KEY }
        if ([string]::IsNullOrWhiteSpace($taskKey)) {
            $taskKey = [Environment]::GetEnvironmentVariable('Deepseek_API_KEY', 'User')
        }
        if ([string]::IsNullOrWhiteSpace($taskKey)) { throw '缺少 Deepseek_API_KEY，评测不会切换为 mock。' }
        $env:RESOLVEFLOW_MODEL_API_KEY = $taskKey.Trim()
    }
    Push-Location $PSScriptRoot
    try { & $python @taskArgs; $taskExit = $LASTEXITCODE }
    finally { Pop-Location }
}
finally { $env:RESOLVEFLOW_MODEL_API_KEY = $previousKey }
exit $taskExit
