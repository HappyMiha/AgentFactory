# Installation execution: first building block

AF-GC-014 is in progress. The installer is not available in the app yet.

`stage_verified_zip` copies a local archive into a new private temporary directory.
It checks the reviewed catalogue's exact download length and SHA-256 before it
opens the ZIP. It bounds the ZIP directory, entry count and total extracted size,
and verifies entry data while extracting. It rejects traversal, Windows aliases,
duplicate paths, file/directory conflicts, links, devices and encrypted entries.
The first profile supports ordinary single-volume ZIP files with ASCII paths and
stored or deflated entries. ZIP64 and other layouts require a separately reviewed
profile. Each newly offered archive needs qualification against these bounds.

Source files must be regular files without links. This is checked before opening
to avoid waiting on a FIFO. On POSIX the open also uses nonblocking/no-follow
flags; the opened descriptor must still be regular and match the observed file.
The FIFO regression runs in a bounded subprocess on POSIX and is explicitly
skipped on Windows, which has no `mkfifo` API. Independent Linux execution is
required for that regression; Windows checks are not substitute evidence.

The pinned official Godot 4.7.2 Windows editor and export-template archives have
now passed hash, size, extraction and cleanup checks on Windows at the reviewed
PR27 commit. They extract to 181,057,040 bytes (two editor files) and 2,072,248,588
bytes (35 template files). The reviewed extraction budgets remain unchanged.
This verifies archive compatibility only: neither executable was launched and
no installation or clean-VM postcondition was qualified. See
[the package evidence](https://github.com/HappyMiha/AgentFactory/pull/27#issuecomment-5558759711).

The result exists only inside the caller's context. Leaving it, including after
a normal exception, removes only that new temporary directory. Existing package
targets and unrelated files are untouched. A hard process kill can leave staging
files; automatic orphan cleanup and crash recovery are not implemented here.

This is a trusted host primitive, not an HTTP installation endpoint. The caller
must supply a private staging parent with no untrusted concurrent writers and a
reviewed catalogue. Link or reparse ancestors are rejected. The caller must keep
the staging root in place throughout the context. File permissions do not provide
isolation from another process running as the same operating-system user.

Before connecting this primitive to the app, the installer must bind the current
persisted AF-GC-013 decision to existing Core policy and the durable operation
journal. It must implement bounded official-source downloads, restart recovery,
atomic publication with owned-file receipts, verified installed/cache inventory,
retry/repair, and the required user-action screens. Staging alone grants no
execution permission and cannot mark an environment ready.

Acceptance of AF-GC-014 still requires the original clean Windows VM tests:
actual Godot/runtime installation, interrupted process and download, disk failure,
restart and verified postconditions. Unit tests with disposable synthetic archives
prove the archive boundary only; they are not evidence of a working installation.

## Persisted installation intent

`InstallationIntents` records an approved, still-current setup proposal in the
existing `MissionOperationJournal`. It does not add another database or operation
queue. The trusted host supplies the authenticated actor and an
`InstallationReview` service. There is no HTTP route for this primitive.

Reservation checks the owner, latest approved snapshot, plan digest, current game
revision, host/workspace, catalogue and capacity. It rechecks expiry after host
observation. These reads and the journal reservation share a database writer lock.
The journal binds the exact proposal, decision ID, stable operation key and current
mission version/revision/epoch/checkpoint/fence. The existing RUNNING control
disposition is required; the game stays in its editable setup draft. No lifecycle
or scheduling gate is bypassed to create the record.

Repeating a still-current reservation returns the same record. After expiry or a
pause, the owner can read that historical record with `view`; attempting a new
reservation still fails current checks. Both responses say
`execution_eligible: false`. The record remains `reserved` with `verify_only`
reconciliation. Nothing starts, consumes a policy approval or installs a package.

The future executor must separately bind this exact intent to current Core
execution permission and durable steps. It must not treat a journal reservation,
an old consent receipt or a successful archive check as permission to run tools.
Crash recovery, publication, download and the final VM acceptance remain open.

## Read-only content checks

`manifest_for_stage` hashes the files in verified private archive staging and
records their relative paths, lengths and SHA-256 values, plus the package and
archive identity. The resulting immutable, bounded, canonical manifest can be
stored by a future trusted publication step. Changed staging inventory is rejected.

`observe_manifest` compares a directory with that expected manifest and reports
`matched`, `conflict`, `absent` or `indeterminate`. Missing or changed files and
unexpected files/directories cannot match. Size/entry limits, unreadable content,
changes detected during a read, links, reparse paths and special files prevent
a successful result. The observer reads files only; it never follows links,
deletes anything or performs a repair. A partial observation is not success.

The expected manifest must come from verified staging or a trusted journal record,
not from a manifest inside the untrusted directory being checked. A valid digest
alone does not authenticate its origin. The host must keep its workspace private
from untrusted concurrent writers; this is not same-user process isolation.
Even a `matched` directory returns `execution_eligible: false` and still needs
an owned publication receipt and actual executable postconditions before setup
can be considered successful. Automatic publication and repair remain future work.

## Exact execution-policy request

`InstallationPolicyBinding` derives an existing `PolicyRequest` from a current
reserved installation intent and trusted host task/worker/runtime/worktree IDs.
It rechecks the owner, actual task project and current intent before returning a
request. The policy contract calls the project ID `mission_id`; this helper uses
the autonomous mission's actual `project_id`, not its separate primary key.

The request uses no workflow run and binds the immutable operation identity and
full request digest into its installation stage ID. A changed intent therefore
cannot consume the previous intent's exact approval. Permissions are limited to
`tool_use` and `worktree_write`; network access or a broader operation would need
a separate reviewed request. Existing policy and approval storage are unchanged.

Constructing this request does not register a worker, establish runtime admission,
request or decide an approval, consume it, or start installation. The host must
obtain the actual execution identities from current trusted configuration and
use the existing approval/admission paths. A returned request is a snapshot:
the future executor must regenerate the current binding immediately before the
effect and must not execute using a stale saved request after plan or host changes.
Tests exercise the existing one-use policy mechanism with synthetic host IDs;
they do not claim a qualified installer runtime or actual installation.

## Publishing verified files on Windows

`prepare_publication` creates an immutable expected receipt from verified archive
staging, the operation identity, request digest and one target directory name.
The trusted executor must save this exact receipt in its durable operation record
before publishing. A receipt found inside a target is not independent proof of
ownership or permission.

`publish_staged` copies and verifies the payload in a private temporary directory
beside the destination. It flushes file contents and calls the trusted host's
authorization boundary immediately before publication. Only literal `True`
permits the rename. The host must recheck the current plan, mission fence and
real runtime admission, consume the exact policy approval, and durably start the
existing operation. This component does not implement those host steps or expose
an application endpoint. A permissive callback in a test is not production
authorization.

The internal destination contains `payload/` and `receipt.json`. Windows rename
publishes that complete directory without replacing any existing destination,
including an empty directory created by a competing process. Existing files
require observation and reconciliation; this method never repairs or deletes
them. The original archive staging remains intact until its own context closes.
The installer must explicitly adopt this internal payload layout before using it
as the final Godot or export-template location; current catalogue targets are not
silently changed by this primitive.

This write profile supports a private local Windows volume only. UNC/device paths
are rejected; the trusted host must also exclude mapped network drives and keep
all parents inaccessible to untrusted concurrent writers. POSIX writes are denied
because ordinary POSIX rename can replace an existing empty directory. Read-only
receipt and payload observation is portable. Neither path checks nor a matching
receipt establish isolation from a hostile process running as the same user.

`observe_publication` compares the complete envelope with the separately trusted
receipt and content manifest. It reports `absent`, `matched`, `conflict` or
`indeterminate`, always with `execution_eligible: false`. After a lost completion
response, a matching envelope provides evidence for the existing journal's
reconciliation path; it does not authorize another write or prove the executable
works. The observer never adopts a different receipt or mutates the target.

Tests use real Windows files, two competing spawned processes, and process
termination immediately before and after the rename. They also cover empty
target conflicts, rejected authorization, changed source files, mixed-case paths,
junction parents, insufficient space and an injected flush failure. A hard kill
may leave private temporary data. Automatic orphan cleanup, end-to-end journal
composition, power-loss/reboot guarantees and actual Windows VM installation
qualification remain open. Publication needs additional space for a second copy
of the extracted payload; the planning budget below includes it.

## Space shown in the installation plan

The plan now budgets for the files that coexist during verified staging and
publication: a new download when needed, the private verification archive,
extracted content, a second payload copy, 8 MiB for publication metadata and
64 MiB of filesystem headroom per changed package. Each step records this
breakdown, and the existing review screen shows the resulting total. The
headroom is a conservative planning allowance, not a measurement or a guarantee
for every filesystem. Actual free space must still be checked before each effect
and write failures must still be handled.

A cached archive saves network transfer and the original download allocation.
It does not remove the need for a private verified archive copy or a publication
copy. Reusing an existing package requires none of these allocations. The total
sums every package's budget, without assuming that earlier temporary files will
already have been cleaned up. Network download totals remain separate.

Previously saved plans and decisions remain readable. Their earlier, smaller
disk budget cannot authorize a new reservation: current proposal comparison
rejects it, and the user must review the new total. This does not automatically
launch an installer or change the final package layout.

## Durable publication evidence and recovery

`InstallationPublicationJournal` stores each package's expected publication
receipt in the existing `MissionOperationJournal`. It links the record to the
reviewed installation intent, verifies the package source and extraction bound,
and derives the relative target from that plan. It creates no parallel operation
log or migration. One intent/package pair has one immutable publication record;
repeated or concurrent reservations return the same record.

Preparation starts by checking the current approved intent. It then verifies the
stage and reserves evidence under the recorded mission scope. This records a
snapshot, not an atomic lock on subsequent source, host or plan changes. A future
executor must revalidate the current intent and establish real policy/admission
at the effect boundary. This service never starts the publisher, consumes an
approval, registers a runtime or creates target directories.

Recovery reads the expected receipt from the journal, checks that the current
trusted host/workspace matches the recorded one, and observes only the planned
relative target. Old evidence remains readable after review expiry. Conflicting
or unreadable files and changed host/workspace identities are preserved and
cannot be adopted as successful publication.

For an operation already marked `unknown`, `reconcile_unknown` uses the existing
journal reconciliation path. A complete matching receipt and payload produce a
`reconciled` publication record. Absence, conflict or uncertainty produce
`needs_attention`, because this component uses `verify_only` and never grants
an automatic retry. Replaying the same reconciliation event creates no second
effect. The parent installation intent remains separate and is not completed.

Tests combine real SQLite reservation/reopen with actual Windows file publication
and a lost completion record. They confirm recovery adopts matching files without
copying again. Fixture authorization in that test only exercises the journal and
filesystem; live runtime admission, one-use policy composition, executable checks
and Windows VM fault acceptance remain open. Every response still reports
`execution_eligible: false`.

## Publication requests for an existing live stage

`InstallationPolicyBinding.publication_request` builds a request for a recorded
publication and an existing mutable `RuntimeLaunch`. It preserves the real run
and stage names and binds the complete publication journal request through
`effect_digest`. The older bootstrap request method remains available unchanged;
it does not acquire live-stage authority through this addition.

The helper checks the current approved intent, reserved publication, assignment
lease, task project, worker/runtime, attempt and managed worktree. The stage must
be running or waiting for approval, and the attempt must not already have consumed
a stage approval. Permissions come from the current task and must match the
launch and include `tool_use` and `worktree_write`.

The installation workspace must be exactly that managed worktree. Permission
to write one worktree cannot silently authorize package files in another project
directory. The host must plan and provision the correct workspace before using
this flow; the helper never relocates files or rewrites the saved plan.

Preparation must run outside a caller transaction because current-intent
reservation uses the existing journal's transaction boundary. An enclosing
transaction is rejected without committing it. The result is still a snapshot,
not an execution grant. It can be passed to the existing live-stage approval
flow; assignment-bound consumption checks the real stage/attempt and exact
effect digest. Reconstructing a request after that attempt's consumption is
rejected and cannot create a second execution opportunity.

If a launch already has an `effect_digest`, it must match the saved publication.
A mismatch is rejected before current-intent reservation, approval or runtime
start. An absent effect is allowed only for preparing a request; this helper
does not add an effect to a launch or upgrade an existing admission.

The trusted host must obtain the saved publication digest before worker admission
and bind that same digest in `AdmissionRequest`, `RuntimeLaunch` and the real
stage's policy request. The existing runtime enforces this agreement. An older
admission without an effect cannot gain permission by changing only the launch.

Tests exercise real SQLite live-stage approval and exact one-use consumption.
An additional composition test starts the actual admitted runtime with a
synthetic counting driver: the saved publication digest reaches the committed
session, the approval is consumed once, and replay calls no second driver. Its
worker qualification is synthetic; no package is published, and the publication
journal stays reserved. This is not an installed or qualified environment.

The opt-in host executor described below combines current intent checks, durable
publication start and real package publication. The request helper alone does
not supply those steps or mark an installation ready.

## Recheck intent without a new reservation

`InstallationIntents.current(mission, actor, operation_id)` checks a saved,
reserved parent intent without writing another journal event or renewing consent.
It uses the same current review checks as reservation: authenticated owner,
exact approved and latest plan, current catalogue and host observation, available
disk space, expiry and a running mission. The saved decision and complete mission
scope must still match, including version, backlog revision, execution epoch,
checkpoint and control fence. Pausing and resuming a mission does not silently
restore an old intent. Historical evidence remains available through `view`.

This helper can run after a stage approval has been consumed. It neither checks
nor grants runtime authority and does not consume that approval again. The host
must separately validate the actual runtime admission, session, exact effect and
publication lifecycle before publishing anything.

Validation acquires the existing SQLite writer lock. Within a caller transaction
it uses a savepoint and keeps that caller's pending work uncommitted on success or
failure. A stale WAL reader cannot upgrade into a successful validation. The
caller must commit its complete execution reservation before an external effect.
Standalone validation releases its lock before returning and is only a snapshot.
Neither mode locks the filesystem or prevents later host and disk changes.

The full reviewed disk budget is still required; this helper does not subtract
unverified staging allocations or infer completed installation steps. A future
executor needs explicit accounting for those allocations and partial progress.
Returned evidence keeps `execution_eligible: false`. Tests cover current and
historical reads, real two-connection isolation, rollback, stale readers and
post-approval validation with a synthetic runtime; they do not execute an installer.

## Publish one package from a running host session

`InstallationExecutor(intents, runtime).publish(...)` is an opt-in Windows host
service. It requires an already admitted, running runtime session, its exact
immutable launch and a verified staged archive. No browser route or default
startup calls it. It does not provision a worker, log in, download an archive or
run an engine executable.

The host passes a saved publication ID and session ID. The service checks the
canonical publication key and parent scope, current approved intent, current
worker admission and lease, exact saved runtime start scope, project/worktree
path, and the matching already-consumed one-use stage approval. An alias journal
record with the same effect hash cannot create another execution opportunity.
Emergency stop and current policy still apply; no second approval is consumed.

The reserved-state check and journal start share one SQLite writer transaction,
which commits before any target directories or temporary package copies are
created. A mission installation-operation lease then tracks this synchronous
call. Current authority is checked before file preparation and again immediately
before the publisher's final rename. A mutable runtime event is recorded before
filesystem work. Two connections racing the same publication can dispatch only
one publisher; running, completed or uncertain records are not executable again.

Only private local fixed Windows drives are accepted. Drive-letter network
mappings, UNC paths, reparse points and existing targets are rejected. Parent
directories are derived from the saved plan and checked as real directories.
The existing publisher copies and verifies the exact manifest, then publishes
the internal `payload/` plus `receipt.json` envelope without overwriting a target.

A verified result completes only the child publication journal record. It does
not complete the parent installation, mark the engine ready or release runtime
capacity. An exception after journal start records `unknown` when possible and
propagates; existing files are preserved. Recovery uses the existing observation
and reconciliation path, never automatic retry. A process killed before it can
record uncertainty can leave `running` and an operation lease; the host must
confirm the stopped process before recovery. Ordinary return or failure closes
the synchronous operation lease, while journal uncertainty remains unresolved.

The method refuses a caller-owned transaction. Database authority and filesystem
rename are not one atomic transaction. Cancellation is checked at the boundary;
copying is not interrupted mid-file. The private workspace must not have hostile
concurrent writers. The full reviewed disk budget is still required in addition
to the publisher's actual free-space check, with no inferred staging credit.

Tests publish real small archives on Windows using real SQLite admission,
approval, journal and operation leases with synthetic worker qualification and
a counting runtime driver. They cover concurrent callers, lost completion and
reconciliation, late expiry, existing-file preservation and mapped-drive denial.
They do not qualify a full Godot installation, process-kill/reboot behavior in a
disposable VM, provider execution, engine launch, export templates or the product
progress/recovery interface. Those remain AF-GC-014 acceptance work.

## Locate a verified published payload

`InstallationPublicationJournal.read_payload(mission, actor, publication_id)`
returns the recorded package/version, archive hash, relative `payload/` path,
verified file manifest and receipt digest. It accepts only canonical publications
whose parent scope matches and whose journal is `completed` or `reconciled`.
An unknown result must be reconciled first, even when the files appear present.
Canonical key and parent-scope validation is shared by all publication readers
and the executor; an alias record cannot stand in for the planned publication.

Every call checks the recorded host/workspace and hashes the actual payload
against the externally saved receipt. A completed status alone, missing files,
modified content or an unreadable/link target cannot produce a verified result.
The returned paths are relative to the trusted workspace and the file manifest
is detached from journal evidence. The method writes no state or journal events.

This is historical artifact discovery, so an expired installation approval does
not hide intact published files. The response reports `publication_verified: true`,
`engine_qualified: false` and `execution_eligible: false`. It does not update the
installation planner's inventory, choose an executable, launch the engine or
renew any permission. Consumers must recheck current authority and file integrity
at their own use boundary; discovery does not lock the filesystem against later
changes. Engine/template path selection and partial-install planning remain open.
