$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Downloading the latest RetroStream image..."
& docker compose pull retrostream
if ($LASTEXITCODE -ne 0) { throw "The RetroStream image update failed." }
& docker compose up --detach retrostream
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not recreate RetroStream." }

$status = "unknown"
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' retrostream 2>$null)
    if ($status -eq "healthy") { Write-Host "RetroStream updated successfully. Your data and cache were preserved."; exit 0 }
    if ($status -in @("exited", "dead")) { break }
    Start-Sleep -Seconds 2
}
& docker compose logs --tail=80 retrostream
throw "RetroStream did not become healthy (status: $status)."
