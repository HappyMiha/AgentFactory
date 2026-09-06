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
