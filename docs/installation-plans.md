# Review an installation before changing the computer

Reviewed AF-GC-013 scope: installation planning and consent for the initial local
Godot Windows profile. Actual recoverable installation belongs to AF-GC-014.
This result does not qualify an installed environment or a complete multi-engine setup.

An installation proposal lists exact packages, their sources, their versions,
their download sizes, their licence steps and the folders they would use. It
never contains a shell script. Creating a proposal does not install software.

## Current component

`agent_factory.installation_plan.build_plan` returns an immutable snapshot with
a SHA-256 digest. `document()` returns a separate copy for a future screen or
storage adapter. `changed_fields` lists changes between two snapshots.

The bundled catalogue currently covers the standard Windows x86-64 Godot
4.7.2 editor and matching export templates. It has a fixed dependency graph.
Unknown packages, dependency conflicts, cycles and overlapping package targets
are rejected. Linux, macOS, Unity, Unreal and local model installation need
their own reviewed entries; they are not silently treated as supported.

Each step is one of:

| Step | Meaning |
| --- | --- |
| Already installed | The observation reports the requested version and archive hash at the planned location. |
| Reuse | The same version and archive hash are reported elsewhere. Do not copy or change it. |
| Install | Propose a separate managed copy. Leave existing software alone. |
| Update | The user explicitly selected a different version of a managed package. Keep the old copy; stage the new copy separately. |
| Manual action | A platform, location, dependency, licence, offline or permission problem needs attention. |

No automatic update of unrelated software occurs. A conflicting installation
at the target is never overwritten. A missing offline archive blocks the step
and its dependants. Cache presence is matched by the exact archive hash.

Inventory locations default to canonical workspace-relative paths. Windows case
and backslash separators are normalized for comparison. Dot segments, duplicate
separators, trailing dots/spaces, absolute paths, short-name aliases and opaque
external labels are not guessed. Such observations make the proposal require
manual action. Callers can explicitly mark opaque labels with
`location_kind: external_label`; this never proves that a target is free. Even a
canonical relative label does not prove filesystem containment or file integrity.

## Sources and disk budget

The catalogue was reviewed on 2026-09-06 against the publisher's
[release metadata](https://api.github.com/repos/godotengine/godot-builds/releases/tags/4.7.2-stable)
and [release page](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable).
The archive byte counts and SHA-256 values come from that metadata. The binaries
were not downloaded or installed as part of this component. These are pinned
reference values, not proof that a local file has passed verification.

The editor download is 86,013,866 bytes. The templates download is 1,281,349,702
bytes. The proposed extraction limits are **project budgets**, 2 GiB and 4 GiB;
they are not measured installed sizes. The additional disk budget includes
uncached downloads plus these extraction limits. Existing cached archives are
assumed to occupy disk already. A future executor must measure free space at
the actual destination and stop before exceeding these limits. Unknown or
insufficient reported free space produces a visible issue.

Godot's pinned [MIT licence](https://github.com/godotengine/godot/blob/4.7.2-stable/LICENSE.txt)
permits commercial use subject to its notice requirements. Preserve the licence
and bundled third-party notices. No Godot purchase or account login is planned.
Future packages requiring licence acceptance must show a manual action.

The proposed targets are isolated workspace staging folders, not a verified
Godot template registration layout. Godot supports editor self-contained mode
through an `_sc_` or `._sc_` file beside the editor, as described in its
[data path documentation](https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html).
Actual extraction, template registration and launch need integration tests.

## Trust and consent boundary

Only reviewed host code supplies the catalogue. Structural URL checks do not
prove publisher identity, so a future API must never accept an arbitrary client
catalogue as trusted configuration. An archive executor must validate the exact
source, redirects, hash, destination containment and archive entries before use.

All inventory, cache and capacity inputs here are caller-reported planning data.
An inventory archive hash does not prove current installed-file integrity. The
proposal always says `execution_eligible: false`. No ready-looking proposal,
Python object or digest is permission to download, elevate or execute.

The digest binds tenant, project, host, workspace, selected packages, locked
dependencies, sources, hashes, licensing steps, permissions, observations and
disk budgets. `require_same_reviewed_content` only compares content. A caller
can compute a digest, so this method is **not an approval issuer**. A future
installer integration must consume the authenticated, persisted decision described
below and re-check current Core execution policy before any change. A different
source, permission, byte count, target or context requires a new decision.

## Local review screen and persistent decisions

From a saved game plan, choose **Переглянути встановлення для збереженого плану**.
The page loads existing state without creating a proposal. **Скласти новий план**
explicitly saves a snapshot from the server's catalogue and current host checks.
It lists packages, source links, sizes, permissions, licensing and target folders.
Changes from the previous snapshot are grouped in plain language. A separate
checkbox and button record approval; rejection has its own button. No installer
or provider is called. A new snapshot does not inherit an earlier decision.

SQLite migration 76 adds immutable plan and decision records to the existing Core
database. A snapshot binds the mission owner, source digest, game-plan revision,
host/workspace fingerprints and exact proposal. Its review period is 15 minutes.
Decisions have unique command IDs and one decision per snapshot; concurrent
conflicting decisions cannot both commit. An exact lost-response retry returns
the original receipt without renewing permission. Records survive app restart.

The normal app installs the routes behind LocalHTTPBoundary. Preparing needs the
current owner's write access; deciding additionally needs a configured authenticated
session or bearer, the approve scope and an owner role. Local-open mode permits
planning but cannot record consent. The server does not accept caller-supplied
catalogues, host reports, actors, snapshots or permission lists from the browser.

Before a new decision, the service checks the latest snapshot, owner, editable
game revision, source, expiry, current catalogue and current host observations
within a database writer transaction. It compares the exact proposal while
retaining the reviewed capacity value, then separately checks current free space
against the reviewed budget. Normal free-space fluctuation does not require new
consent if enough space remains. A changed scope, conflicting target or insufficient
capacity rejects approval and asks for a new review. Historical receipts remain
visible; they are not current execution permissions.

The default host probe reads the actual workspace drive's free capacity and fixed
managed target paths. It does not launch tools or scan arbitrary user directories.
Existing targets have unknown provenance and are conflicts, including blocking
ancestor files; links and Windows reparse points need manual resolution. It never
claims a discovered editor is usable. Initial Windows x86-64 staging is supported;
other platforms show a manual action. Offline preparation has no verified cache
adapter yet, so it cannot silently approve a missing archive.

## Follow-up work beyond the reviewed planning profile

- Add verified installed-package/cache receipts so reuse and offline plans can be
  offered from actual host evidence rather than caller fixtures.
- Expand the reviewed catalogue and licensing flow for supported local models
  and further engines/platforms.
- Accept actual setup evidence in AF-GC-014 and later environment qualification
  before calling the complete environment ready.

The original AF-GC-013 criteria are covered for this initial profile: pinned
catalogue and change scope, all five planning classifications, and persistent
digest-bound decisions. Validation includes plan differences, source/hash changes,
dependency conflict, no-admin/offline fixtures and the default UI/API recovery
paths. Independent Windows and Ubuntu reviews are recorded in PRs 24 and 25.
The unknown installed/cache state is deliberately manual; it is not a claim of
verified reuse. Broadening that support must preserve the same review boundary.

AF-GC-014 then owns actual recoverable installation through Core's operation
journal and policy checks, bounded archive extraction, crash recovery, cleanup
and disposable Windows installation tests. This proposal component does not
claim those results or qualify a runnable game environment.

## Validation

`test_installation_plan` covers dependency ordering and conflict, changed source
and checksum, changed permissions and size, content-review invalidation, isolated
updates, target conflicts, offline cache, no-admin, licensing, unsupported
platforms, disk uncertainty, bounded input and immutable snapshots. It uses
fixtures; it never downloads a package or changes the host environment.
`test_installation_review`, `test_installation_web` and
`test_installation_browser` additionally cover database upgrade preservation,
restart, authenticated ownership/scopes, conflicting concurrent decisions,
source/host/space changes, explicit review/rejection, lost responses, and the
default app in real Chromium at 390px. Synthetic host fixtures exercise the
approve branch; a separate filesystem probe test reads a disposable local folder.
