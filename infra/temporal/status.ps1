[CmdletBinding()]
param()

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $root "docker-compose.yml"
$namespace = if ($env:TEMPORAL_NAMESPACE) { $env:TEMPORAL_NAMESPACE } else { "agentfactory" }

Write-Host "AgentFactory Temporal container status"
docker compose --file $compose ps

$postgres = "UNAVAILABLE"
$temporal = "UNAVAILABLE"
$ui = "UNAVAILABLE"
$namespaceStatus = "UNAVAILABLE"

docker compose --file $compose exec -T postgresql sh -c 'pg_isready -U "$POSTGRES_USER"' *> $null
if ($LASTEXITCODE -eq 0) { $postgres = "READY" }

docker compose --file $compose exec -T temporal-admin-tools temporal operator cluster health --address temporal:7233 *> $null
if ($LASTEXITCODE -eq 0) {
    $temporal = "READY"
    docker compose --file $compose exec -T temporal-admin-tools temporal operator namespace describe --namespace $namespace --address temporal:7233 *> $null
    if ($LASTEXITCODE -eq 0) { $namespaceStatus = "READY" } else { $namespaceStatus = "MISSING" }
}

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080" -TimeoutSec 3
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { $ui = "READY" }
} catch {}

Write-Host ""
Write-Host "PostgreSQL      : $postgres"
Write-Host "Temporal Server : $temporal"
Write-Host "Temporal UI     : $ui"
Write-Host "Namespace       : $namespace ($namespaceStatus)"
Write-Host "Address         : localhost:7233"
Write-Host "UI URL          : http://localhost:8080"
