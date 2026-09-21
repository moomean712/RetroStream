$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$line = "--------------------------------------------------"
Write-Host $line
Write-Host "RetroStream Docker Setup"
Write-Host $line
Write-Host

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed."
    Write-Host
    Write-Host "Install Docker Desktop, start it, then run this installer again:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\docker\install-docker.ps1"
    exit 1
}
Write-Host "Docker .............. OK"
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Compose is missing. Update/install Docker Desktop, then run this installer again."
}
Write-Host "Docker Compose ...... OK"
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Desktop is not running (or Docker cannot be reached). Start it and try again."
}

$detected = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Sort-Object InterfaceMetric |
    Select-Object -ExpandProperty IPAddress -First 1
$current = $null
$currentWeb = $null
$currentStream = $null
if (Test-Path .env) {
    $envLines = Get-Content .env
    $match = $envLines | Where-Object { $_ -match '^RETROSTREAM_HOSTNAME=' } | Select-Object -Last 1
    if ($match) { $current = $match.Substring($match.IndexOf('=') + 1) }
    $match = $envLines | Where-Object { $_ -match '^RETROSTREAM_WEB_PORT=' } | Select-Object -Last 1
    if ($match) { $currentWeb = $match.Substring($match.IndexOf('=') + 1) }
    $match = $envLines | Where-Object { $_ -match '^RETROSTREAM_STREAMING_PORT=' } | Select-Object -Last 1
    if ($match) { $currentStream = $match.Substring($match.IndexOf('=') + 1) }
}
$default = if ($current) { $current } else { $detected }
$webPort = if ($currentWeb) { $currentWeb } else { '8780' }
$streamingPort = if ($currentStream) { $currentStream } else { '8781' }
Write-Host
Write-Host "Detected LAN address: $(if ($detected) { $detected } else { 'not found' })"
Write-Host
Write-Host "How will your retro PCs reach this server?"
do {
    $entered = Read-Host "[$default]"
    $hostName = if ([string]::IsNullOrWhiteSpace($entered)) { $default } else { $entered.Trim() }
    $valid = $hostName -match '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$'
    if (-not $valid) { Write-Host "Enter an IPv4 address or LAN DNS name only (for example 192.168.1.50)." }
} until ($valid)

$lines = if (Test-Path .env) {
    @(Get-Content .env | Where-Object { $_ -notmatch '^RETROSTREAM_(HOSTNAME|WEB_PORT|STREAMING_PORT)=' })
} else { @() }
$lines += "RETROSTREAM_HOSTNAME=$hostName"
$lines += "RETROSTREAM_WEB_PORT=$webPort"
$lines += "RETROSTREAM_STREAMING_PORT=$streamingPort"
[IO.File]::WriteAllLines((Join-Path (Get-Location) '.env'), $lines, [Text.UTF8Encoding]::new($false))

Write-Host
Write-Host "Starting RetroStream..."
& docker compose pull retrostream
if ($LASTEXITCODE -eq 0) { & docker compose up --detach retrostream }
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not start RetroStream." }

$status = "unknown"
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' retrostream 2>$null)
    if ($status -eq "healthy") { break }
    if ($status -in @("exited", "dead")) { break }
    Start-Sleep -Seconds 2
}
if ($status -ne "healthy") {
    & docker compose logs --tail=80 retrostream
    throw "RetroStream did not become healthy (status: $status)."
}

$logs = (& docker compose logs --no-color retrostream 2>$null) -join "`n"
$matches = [regex]::Matches($logs, '[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}')
$code = if ($matches.Count) { $matches[$matches.Count - 1].Value } else { $null }
Write-Host
Write-Host $line
Write-Host "RetroStream is running!"
Write-Host
Write-Host "Open:"
Write-Host
Write-Host "http://${hostName}:${webPort}/setup"
if ($code) {
    Write-Host
    Write-Host "First-run setup code:"
    Write-Host
    Write-Host $code
} else {
    Write-Host
    Write-Host "No new setup code was found. Setup may already be complete."
    Write-Host 'Run "docker compose logs retrostream" to inspect startup messages.'
}
Write-Host
Write-Host "Streaming port: $streamingPort"
Write-Host
Write-Host "Your data and playlists are stored safely and survive container updates."
Write-Host $line
