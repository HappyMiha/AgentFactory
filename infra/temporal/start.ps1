[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $root "docker-compose.yml"

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start Docker Desktop, then run this command again."
}

docker compose --file $compose up --detach --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not start Temporal." }

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    & (Join-Path $root "health.ps1") *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($LASTEXITCODE -ne 0) {
    docker compose --file $compose ps
    throw "Temporal did not become healthy within $TimeoutSeconds seconds."
}

Write-Host ""
Write-Host "AgentFactory Temporal"
Write-Host ""
Write-Host "Temporal Server : READY"
Write-Host "PostgreSQL      : READY"
Write-Host "Temporal UI     : READY"
Write-Host ""
Write-Host "Temporal Address:"
Write-Host "localhost:7233"
Write-Host ""
Write-Host "Temporal Web UI:"
Write-Host "http://localhost:8080"
