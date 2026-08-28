# Temporal Worker versioning and replay runbook

This runbook is the release gate for `AutonomousMissionWorkflow`. These missions can outlive one process and one software release, so a green unit suite alone is not enough to replace a Worker build.

## Pinned compatibility baseline

- Python SDK: `temporalio==1.31.0`
- Temporal Server and Admin Tools: `1.31.2`
- Default deployment name: `agentfactory-autonomous`
- Current continue-as-new patch: `af-amm-017-safe-rollover-v1`
- Carry-over emitted by new runs: schema v2; schema v1 remains replay-only

Do not change the SDK or Server pin in the same release as a Workflow command change unless both old and representative production histories replay under the complete proposed dependency set.

## Build identity rules

`TEMPORAL_WORKER_BUILD_ID` must be non-empty, at most 255 characters, immutable, and unique to one deployable code/dependency bundle. Never reuse a build ID after changing Workflow code, Activity contracts, the Python SDK, or payload conversion. A recommended form is `agentfactory-<release>-<commit>-temporal-sdk-1.31.0`.

Legacy routing remains the default:

```powershell
$env:TEMPORAL_WORKER_BUILD_ID = "agentfactory-0.1.0-<commit>-temporal-sdk-1.31.0"
$env:TEMPORAL_WORKER_VERSIONING_ENABLED = "false"
```

Enable Worker Deployments only after the target Temporal cluster and operator procedure have been qualified:

```powershell
$env:TEMPORAL_WORKER_DEPLOYMENT_NAME = "agentfactory-autonomous"
$env:TEMPORAL_WORKER_BUILD_ID = "agentfactory-0.1.1-<commit>-temporal-sdk-1.31.0"
$env:TEMPORAL_WORKER_VERSIONING_ENABLED = "true"
```

AgentFactory creates `WorkerDeploymentConfig` with `PINNED` as the default behavior. Existing runs therefore remain on their assigned version. When Temporal reports that the target deployment changed, the parent still waits for an accepted safe boundary; its next continued run explicitly uses `AUTO_UPGRADE`. No active mutation or child is moved between builds.

## Workflow code-change policy

1. Classify the change. Query-only output changes normally need replay coverage but no patch. Any changed command order, Activity/child scheduling, timer, wait, Signal behavior, or continue-as-new decision requires a named `workflow.patched()` branch.
2. Add the patch before deploying code that emits the new command sequence. Patch IDs are permanent audit identifiers; do not rename or reuse them.
3. Keep old dataclass fields and schema decoders needed by retained histories. New runs may emit a new schema only after old input is still decodable.
4. Capture representative histories from every currently routed build and phase, including waiting, active child, control handling, epoch handoff, retry, and completed histories.
5. Replay those histories against the exact release environment. Any nondeterminism blocks rollout.
6. Deploy the new Worker build without stopping the compatible old build. Confirm pollers and Activity registration, then make the new deployment version eligible through the cluster's reviewed operator process.
7. Observe at least one safe continue-as-new, verify the SQLite chain predecessor/build IDs and Search Attributes, and verify accepted mutation counts did not repeat before draining the old Worker.

Run the repository replay and rollover gate with:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_autonomous_history_rollover
& .\.venv\Scripts\python.exe -m unittest discover -s tests
```

`AutonomousHistoryReplayTests` generates a frozen pre-patch history and replays it with the current Workflow definition. `AutonomousHistoryRolloverTemporalTests` forces a safe-boundary threshold of one, crosses three runs, replaces Worker `v1` with `v2`, queries each exact run, and proves two accepted planning mutations were invoked exactly twice.

## Patch retirement

Do not remove a patch merely because Temporal visibility no longer lists an old run. First prove from `autonomous_mission_temporal_runs`, deployment inventory, and retention policy that no open execution or replay/archival obligation can contain pre-patch history. In a later release, replace the active compatibility branch with `workflow.deprecate_patch(<id>)`, replay the same history corpus, deploy it, and wait through the full retention and operational rollback window. Physical code removal is a separate later release with another replay gate.

## Visibility and retention

The namespace defaults to seven-day retention. Each retained run is indexed by `AgentFactoryMissionId`, `AgentFactoryProjectId`, `AgentFactoryMissionIdentity`, `AgentFactoryMissionKey`, `AgentFactoryChainSequence`, `AgentFactoryMissionPhase`, and `AgentFactoryMissionDisposition`. The compact memo repeats mission/project/chain identity and supports direct description when advanced visibility is unavailable.

Temporal visibility is not the domain audit source. Migration 69's immutable `autonomous_mission_temporal_runs` table records every run ID, predecessor, first run, exact mission scope, Worker build, rollover reason, history/safe-boundary counters, accepted-mutation count, and SHA-256 digest. Use those run IDs for direct history/archive lookup after visibility expiry, subject to the deployment's archival policy. AgentFactory data retention or deletion must treat that ledger and normal audit events explicitly.

## Rollback

1. Stop making the new deployment version eligible; keep its evidence and do not reuse its build ID.
2. Keep the old compatible Worker polling until all executions routed to it are stable.
3. If a new run already started on the new build, do not force it onto incompatible code. Restore a Worker with that exact build or deploy a forward-compatible repair build after replay succeeds.
4. Never delete, rewrite, or resequence `autonomous_mission_temporal_runs`. A failed registration or digest/scope mismatch is an incident requiring investigation, not a row-edit request.
5. Confirm current mission version, fencing token, run predecessor, accepted-mutation count, and planning/child idempotency records before resuming routing.
