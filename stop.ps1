[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot 'scripts/project.ps1') -Command stop
exit $LASTEXITCODE
