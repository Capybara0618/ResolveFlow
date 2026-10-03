[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$NoBrowser
)

& (Join-Path $PSScriptRoot 'scripts/project.ps1') -Command start @PSBoundParameters
exit $LASTEXITCODE
