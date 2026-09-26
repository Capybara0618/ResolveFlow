param([Parameter(Mandatory=$true)][string]$PackDirectory)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pack = (Resolve-Path -LiteralPath $PackDirectory).Path
if (-not (Test-Path -LiteralPath (Join-Path $pack 'pack.json'))) { throw 'REPLAY_MISS: pack.json absent' }
docker build --file (Join-Path $root 'infra/replay.Dockerfile') --tag resolveflow-replay:local $root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges `
    --user 10001:10001 --pids-limit 64 --memory 1g --cpus 1 `
    --tmpfs /tmp:rw,nosuid,noexec,size=32m --mount "type=bind,src=$pack,dst=/pack,readonly" `
    resolveflow-replay:local
exit $LASTEXITCODE
