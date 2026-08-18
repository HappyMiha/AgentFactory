[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $root "docker-compose.yml"
$target = "AgentFactory Temporal containers and persistent PostgreSQL history volume"

if (-not $Force -and -not $PSCmdlet.ShouldProcess($target, "Delete and recreate")) {
    Write-Host "Reset cancelled."
    exit 0
}

docker compose --file $compose down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not reset Temporal." }
& (Join-Path $root "start.ps1")
