[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $root "docker-compose.yml"
$namespace = if ($env:TEMPORAL_NAMESPACE) { $env:TEMPORAL_NAMESPACE } else { "agentfactory" }

try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker is unavailable" }

    docker compose --file $compose exec -T postgresql sh -c 'pg_isready -U "$POSTGRES_USER"' *> $null
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is unavailable" }

    docker compose --file $compose exec -T temporal-admin-tools temporal operator cluster health --address temporal:7233 *> $null
    if ($LASTEXITCODE -ne 0) { throw "Temporal is unavailable" }

    docker compose --file $compose exec -T temporal-admin-tools temporal operator namespace describe --namespace $namespace --address temporal:7233 *> $null
    if ($LASTEXITCODE -ne 0) { throw "Temporal namespace '$namespace' is unavailable" }

    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080" -TimeoutSec 5
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) {
        throw "Temporal UI returned HTTP $($response.StatusCode)"
    }
    exit 0
}
catch {
    Write-Error "AgentFactory Temporal health check failed: $($_.Exception.Message)"
    exit 1
}
