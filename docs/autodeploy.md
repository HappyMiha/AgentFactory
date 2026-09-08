# Test deployment and shared identity

The previous generic shell-command workflow has been replaced. GitHub Actions
qualifies the exact main revision; one controller on HappyDucky02 polls both
repositories every 60 seconds and performs the actual Docker deployment.

## Safety contract

- Persistent named data volumes are reused; they are never restored during code rollback.
- Before a release, the previous Docker image is archived and live SQLite databases
  are copied using SQLite's online backup API with an integrity check. WAL/SHM files
  are not copied independently. Ordinary files that change while copying fail the backup.
- Each SQLite snapshot is transaction-consistent. Multiple databases and files are
  not a single global transaction; disaster recovery needs explicit reconciliation.
- A candidate starts on a disposable snapshot with networking disabled. An authenticated
  read exercises database initialization. Any change to an existing database schema
  blocks automatic deployment.
- A stable streaming gateway reads routing atomically for each new request.
  Existing calls retain their original upstream. Old application containers and all
  game/AI workers remain running. There is no compose stop/restart/down or volume prune.
- Failed activation switches new requests back to the previous running image.
  New client writes remain in the same live volume. Controller crash recovery also
  restores routing only. Failed releases are retained for investigation.
- Retained containers are bounded. At the configured limit, deployment blocks until
  an operator has verified that older jobs are finished and retires those releases.
  This favors preserving work over automatic resource reclamation.
- Automatic schema migrations, destructive data rollback and worker restarts are not supported.
  These require an application-specific compatibility and drain plan.

## Single deployment page

The gateway serves /deployments on both test domains. The page reads the same
authenticated /deployments/status endpoint: project, revision, current phase,
success/failure, rollback result, error text and release notes. It does not store
GitHub tokens in the browser. GitHub Deployments receives matching summary statuses.

## Shared identity

id.lokvetia.com hosts the single invitation-only identity service and the shared
/profile and /organizations pages. Both applications redirect to this service.
Passwords, users and invitations exist only in its persistent accounts.sqlite3.
Application databases contain opaque session references, not copies of users.

Browser sign-in uses short-lived single-use authorization codes, exact redirect
allowlists, a browser-bound state cookie and PKCE. Application credentials and
opaque grants use authenticated server-to-server endpoints, which are not routed
publicly. This is a private integration for these two clients, not a general OIDC provider.

Remembered sessions expire after 30 days and remain valid across releases.
Signing out revokes the central session and all its application grants.
Existing configured operator identity is retained for the administrator so
existing briefs, ownership and audit records remain accessible.

The current organization is one shared test organization. Invited members receive
read/write membership, not administrator/control permissions. Separate tenant
deployments and organization isolation must precede public self-registration.

## Installation

The runtime bundle is ops/test-deploy in Core. Keep private configuration,
credentials, release checkouts and backups outside the Git checkout. Run:

```powershell
python scripts/autodeploy.py --config C:/path/to/private/config.json --watch
```

Install it as an at-logon task for the Docker Desktop owner with restart-on-failure.
It needs Docker, Git and the existing GitHub CLI login. It does not require a public
self-hosted Actions runner. Never mount the Docker socket into application,
identity or gateway containers.

Required config keys: state_root, runtime_bundle, network, initial_routes and projects.
Each project has id, name, repository, service, host, volume, access_token_file,
environment and secret_mounts. Service is identity, lokvetia or lokiravia.

The gateway uses a read-only mount of the public status/routing directory.
Cloudflare routes the existing two domains and id.lokvetia.com to the gateway.
Do not change existing application ports or stop their containers during onboarding.

The source controller is versioned in Git. Updating the controller itself is an
operator task; stopping only the controller does not stop applications or workers.
