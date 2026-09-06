# Qualified worker admission

`WorkerAdmissionService` is an opt-in Core boundary for an authenticated host or
Cloud control plane. It checks a worker and reserves its capacity before work
starts. Existing Core assignments, leases, attempts and fencing tokens remain
the execution authority. This service does not create another scheduler.

## Trusted setup

The host configures one capacity pool for each physical executor and binds every
logical worker alias on that executor to the same pool. Pool capacity and allowed
runtimes come from the host. A worker cannot supply its own capacity. All members
of a fleet must use the same Core database for this limit to apply. Two separate
databases cannot coordinate one physical machine with this API.

The host also binds a Core project to its verified tenant. Core projects do not
otherwise have a tenant owner. A tenant string, actor name or evidence digest is
not proof of identity. Cloud must authenticate the caller and resolve the project
and worker from trusted records before calling these in-process methods. Do not
expose registration or stop reconciliation as unauthenticated worker endpoints.

Use `configure_pool`, `bind_worker` and `bind_project` with the current expected
version. Stale updates fail. Project ownership cannot be reassigned. Policy can
be disabled or updated; previous admission versions then lose authority. An
occupied worker cannot be moved to a fresh pool to evade its existing occupancy.
Registering a worker with live legacy work is rejected.
Failed legacy sessions are also treated as unresolved, even when an external
identity is known. This slice has no legacy stop-reconciliation API. A fresh
logical name is not proof that the physical machine is empty: the trusted host
must verify old work is stopped and keep the same canonical pool for all aliases.

## One admission transaction

Build an immutable `AdmissionRequest` with an operation ID, trusted tenant and
project, task, run and stage key, worker, runtime, provider, role, required
capabilities, exact qualification ID and expected policy versions. Provider IDs
and runtime IDs are separate values. A stage key belongs to one run; the receipt
also records its numeric database ID.

`admit` checks the latest qualification, its expiry and capabilities, the current
worker lifecycle, pool policy, project association, workflow dependencies and
available capacity. It creates the existing assignment, lease and first attempt
together with an admission receipt in one SQLite `BEGIN IMMEDIATE` transaction.
A failure rolls back the whole operation. Qualification timestamps are parsed
as UTC instants, including the older SQLite timestamp format.

The same request ID and content return the existing receipt. Changed content with
that ID fails. Replaying an expired, released or revoked receipt does not create
another attempt. Its `active` field is separate from its capacity occupancy.
Registered workers and projects must use this boundary; the old public claim
and extra-attempt methods cannot bypass it. Unregistered trusted local workers
on unregistered projects keep the legacy API.

## Start and recovery

Provision a managed worktree after admission through the existing Core API. At
launch it must be ready and match the receipt's task, assignment, attempt, owner,
lease and fence. The persisted execution context must match the admitted run as
well as the task and assignment. A missing `RuntimeBinding` cannot disable these
checks: Core finds the admission through the stored assignment.

`WorkerRuntime.start` reserves one session for the admitted attempt before calling
an external driver. An identical concurrent or repeated start returns that same
session; different launch content fails. Replay does not consume another approval
or call the driver again. Mutable execution still needs the existing scoped
approval and, where applicable, the mission control fence.

A `starting` session may mean that a driver accepted a request but its response
was lost. It is an uncertain outcome, not an invitation to retry the external
start. This is at-most-one dispatch reservation, not a claim of exactly-once
remote execution. Even a failure before dispatch conservatively retains its
reservation until trusted reconciliation.

New admissions and launches require an active worker. Draining permits existing
bounded lease renewal but stops new starts. Quarantined or offline workers cannot
renew, start, resume or publish mutable output. Renewal never extends past the
current qualification or pool expiry. Updating registration policy or replacing
the qualification invalidates the old admission. Only the first active-to-draining
lifecycle transition preserves existing authority. Clearing quarantine or
returning a drained worker to active does not revive old admissions.

## Capacity is released only with stop evidence

Lease expiry, missed heartbeats, a failed driver response and a local cancelled
session do not prove that an external process stopped. Capacity remains occupied.
The host must inspect the exact executor operation, terminate or otherwise prove
that it cannot continue, and record `reconcile_stopped` with the exact admission
ID, fence and evidence digest. This method records that trusted result; it does
not itself contact or kill the process.

The evidence must also prove that any pending launcher is fenced or quiesced:
seeing no process while an old start request is still in flight is insufficient.
A local database transaction cannot cancel a remote call after dispatch. The
host adapter must enforce this stop protocol before it reports success. Otherwise
an old in-flight request could start after capacity was reused. This Core change
does not qualify that host protocol.

Reconciliation cancels remaining authority for that admission and releases only
its occupancy. An old acknowledgement cannot release a later admission. Replaying
the same stop evidence is safe; replacing it with different evidence fails.
Detailed process evidence stays in the host's protected evidence store, not in
public task metadata.

## Qualification limits

Migration 75 adds linked admission records without replacing existing tables.
The tests use temporary SQLite databases, independent connections and synthetic
drivers. They cover competing claims, rollback, exact scope, policy expiry,
replay, lost responses and retained capacity. They do not certify a remote host,
its sandbox, a model provider, Unreal, cloud deployment or process termination.

Cloud's worker integration must pin an accepted Core revision, implement its
authenticated project mapping and collect real host and stop evidence before it
can claim deployment readiness. See backlog item `AF-GC-043`; the existing Cloud
worker qualification task remains a separate acceptance result.
