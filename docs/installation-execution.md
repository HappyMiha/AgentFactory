# Installation execution: first building block

AF-GC-014 is in progress. The installer is not available in the app yet.

`stage_verified_zip` copies a local archive into a new private temporary directory.
It checks the reviewed catalogue's exact download length and SHA-256 before it
opens the ZIP. It bounds the ZIP directory, entry count and total extracted size,
and verifies entry data while extracting. It rejects traversal, Windows aliases,
duplicate paths, file/directory conflicts, links, devices and encrypted entries.
The first profile supports ordinary single-volume ZIP files with ASCII paths and
stored or deflated entries. ZIP64 and other layouts require a separately reviewed
profile. Actual Godot archives still need qualification against these bounds.

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
