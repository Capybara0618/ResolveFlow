[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot 'scripts/project.ps1') -Command status
exit $LASTEXITCODE
