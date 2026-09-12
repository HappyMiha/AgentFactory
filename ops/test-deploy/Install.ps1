param(
    [Parameter(Mandatory=$true)][string]$ServerRoot,
    [Parameter(Mandatory=$true)][string]$Python,
    [switch]$ConfigureOnly,
    [switch]$StartGateway
)
$ErrorActionPreference = 'Stop'
$server = (Resolve-Path -LiteralPath $ServerRoot).Path
$root = Join-Path $server 'autodeploy'
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
foreach ($folder in @($root, "$root/runtime", "$root/runtime/progress/scripts", "$root/runtime/progress/src/agent_factory", "$root/public", "$root/secrets")) {
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
}
Copy-Item -LiteralPath "$source/scripts/autodeploy.py" -Destination "$root/controller.py"
Copy-Item -LiteralPath "$source/docs/deploy-dashboard.html" -Destination "$root/public/dashboard.html"
Copy-Item -LiteralPath "$source/docs/progress-dashboard.html" -Destination "$root/public/progress.html"
Copy-Item -LiteralPath "$source/scripts/progress_report.py" -Destination "$root/runtime/progress/scripts/progress_report.py"
foreach ($name in @('__init__.py','backlog.py','progress.py')) {
    Copy-Item -LiteralPath "$source/src/agent_factory/$name" -Destination "$root/runtime/progress/src/agent_factory/$name"
}
foreach ($name in @('serve.py','domain_adapter.py','snapshot.py','gateway.py','Dockerfile.core','Dockerfile.cloud')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination "$root/runtime/$name"
}
function Write-PrivateSecret([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        $bytes = New-Object byte[] 48
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllText($Path, [Convert]::ToBase64String($bytes), [Text.UTF8Encoding]::new($false))
    }
}
foreach ($name in @('identity-token.txt','core-sso.txt','cloud-sso.txt')) { Write-PrivateSecret "$root/secrets/$name" }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls "$root/secrets" /inheritance:r /grant:r "${user}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect identity credential files' }
if (-not (Test-Path -LiteralPath "$root/secrets/clients.json")) {
    $clients = @{
        core = @{name='Lokvetia Core';origin='https://test.lokvetia.com';secret=[IO.File]::ReadAllText("$root/secrets/core-sso.txt")}
        cloud = @{name='Lokiravia';origin='https://test.lokiravia.com';secret=[IO.File]::ReadAllText("$root/secrets/cloud-sso.txt")}
    }
    [IO.File]::WriteAllText("$root/secrets/clients.json", ($clients | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}
if (-not (Test-Path -LiteralPath "$root/config.json")) {
    # The application runs in a container here, and says so in every report:
    # a hardware scan from this process describes the container, not a user's PC.
    $common = @{LOKVETIA_IDENTITY_ORIGIN='https://id.lokvetia.com';LOKVETIA_IDENTITY_INTERNAL='http://lokvetia-deploy-gateway:8080';LOKVETIA_ORGANIZATION='lokvetia';LOKVETIA_SSO_SECRET_FILE='/run/secrets/sso_client';LOKVETIA_MACHINE_KIND='web_container';LOKVETIA_MACHINE_NAME='test.lokvetia.com'}
    $coreEnv = $common.Clone(); $coreEnv.LOKVETIA_SSO_CLIENT='core'; $coreEnv.LOKVETIA_SSO_ORIGIN='https://test.lokvetia.com'
    $cloudEnv = $common.Clone(); $cloudEnv.LOKVETIA_SSO_CLIENT='cloud'; $cloudEnv.LOKVETIA_SSO_ORIGIN='https://test.lokiravia.com'
    $config = @{
        state_root=$root;runtime_bundle="$root/runtime";network='lokvetia-test_default';poll_seconds=60;max_retained_containers_per_project=8;keep_releases=2
        progress=@{projects=@(
            @{id='core';name='Lokvetia Core';repository='HappyMiha/Lokvetia-Core';manifests=@('examples/development-backlog.json','examples/game-creator-backlog.json','examples/autonomous-mission-backlog.json','docs/evolution/backlog.json')},
            @{id='cloud';name='Lokiravia';repository='HappyMiha/Lokiravia';manifests=@('examples/agentfactory-cloud-backlog.json','docs/evolution/backlog.json')}
        )}
        initial_routes=@{
            'test.lokvetia.com'=@{container='lokvetia-test-lokvetia-1';sha='e74cb1a';project='core'}
            'test.lokiravia.com'=@{container='lokvetia-test-lokiravia-1';sha='ff76420';project='cloud'}
        }
        projects=@(
            @{id='identity';name='Lokvetia Account';repository='HappyMiha/Lokvetia-Core';service='identity';host='id.lokvetia.com';volume='lokvetia-identity-data';access_token_file="$root/secrets/identity-token.txt";environment=@{AGENT_FACTORY_API_ACTOR='HappyDucky02-test';LOKVETIA_ORGANIZATION='lokvetia'};secret_mounts=@(@{source="$root/secrets/clients.json";target='/run/secrets/identity_clients'})},
            @{id='core';name='Lokvetia Core';repository='HappyMiha/Lokvetia-Core';service='lokvetia';host='test.lokvetia.com';volume='lokvetia-test_lokvetia-data';access_token_file="$server/secrets/lokvetia-token.txt";environment=$coreEnv;secret_mounts=@(@{source="$root/secrets/core-sso.txt";target='/run/secrets/sso_client'})},
            @{id='cloud';name='Lokiravia';repository='HappyMiha/Lokiravia';service='lokiravia';host='test.lokiravia.com';volume='lokvetia-test_lokiravia-data';access_token_file="$server/secrets/lokiravia-token.txt";environment=$cloudEnv;secret_mounts=@(@{source="$root/secrets/cloud-sso.txt";target='/run/secrets/sso_client'})}
        )
    }
    [IO.File]::WriteAllText("$root/config.json", ($config | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}
if ($ConfigureOnly) { Write-Output 'Private configuration created. No application was restarted.'; exit 0 }
& docker volume inspect lokvetia-identity-data *> $null
if ($LASTEXITCODE -ne 0) {
    & docker volume create lokvetia-identity-data | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create identity data volume' }
    & docker run --rm --network none --user 0 --mount type=volume,source=lokvetia-identity-data,target=/data,volume-nocopy --entrypoint python lokvetia-core:test-e74cb1a -c "import os;os.chown('/data',10001,10001)"
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize new identity volume' }
}
if ($StartGateway) {
    $routes = [IO.File]::ReadAllText("$root/public/routes.json") | ConvertFrom-Json
    $image = $routes.'test.lokvetia.com'.image
    if (-not $image) { throw 'Run one successful controller cycle before starting the gateway' }
    & docker container inspect lokvetia-deploy-gateway *> $null
    if ($LASTEXITCODE -ne 0) {
        & docker run -d --name lokvetia-deploy-gateway --network lokvetia-test_default --restart unless-stopped --read-only --cap-drop ALL --security-opt no-new-privileges:true --memory 256m --publish 127.0.0.1:8780:8080 --mount "type=bind,source=$root/public,target=/state,readonly" --entrypoint python $image /app/gateway.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not start streaming gateway' }
    }
}
$runner = @"
`$ErrorActionPreference = 'Stop'
& '$Python' '$root/controller.py' --config '$root/config.json' --watch *>> '$root/controller.log'
exit `$LASTEXITCODE
"@
[IO.File]::WriteAllText("$root/Run-Controller.ps1", $runner, [Text.UTF8Encoding]::new($false))
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$root/Run-Controller.ps1`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName 'Lokvetia-Test-Autodeploy' -Action $action -Trigger $trigger -Settings $settings -User $user -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName 'Lokvetia-Test-Autodeploy'
Write-Output 'Autodeploy controller scheduled for the Docker Desktop owner. Applications and workers were not restarted.'
