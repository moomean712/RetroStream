param([switch]$IncludeCache)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$destination = Join-Path (Get-Location) "backups\retrostream-$stamp"
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$wasRunning = (& docker inspect --format '{{.State.Running}}' retrostream 2>$null) -eq 'true'

try {
    Write-Host "Pausing RetroStream briefly for a consistent SQLite backup..."
    if ($wasRunning) { & docker compose stop retrostream *> $null }
    & docker compose cp retrostream:/data/. (Join-Path $destination 'data')
    if ($LASTEXITCODE -ne 0) { throw "Could not copy RetroStream data." }
    if ($IncludeCache) {
        & docker compose cp retrostream:/cache/. (Join-Path $destination 'cache')
        if ($LASTEXITCODE -ne 0) { throw "Could not copy RetroStream cache." }
    }
} finally {
    if ($wasRunning) { & docker compose start retrostream *> $null }
}
Write-Host "Backup complete: $destination"
Write-Host "Keep this folder private; it contains administrator and session state."
