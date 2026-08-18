[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
docker compose --file (Join-Path $root "docker-compose.yml") stop
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not stop Temporal." }
Write-Host "Temporal containers stopped. PostgreSQL history volume was preserved."
