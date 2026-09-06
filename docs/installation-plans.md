# Review an installation before changing the computer

Status: AF-GC-013 contract component. The full task is not complete.

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
integration must authenticate the person, persist their decision, bind it to
this digest and re-check current Core policy before any change. A different
source, permission, byte count, target or context requires a new decision.

## Remaining AF-GC-013 work

- Add a simple installation review screen to the normal setup flow.
- Add authenticated, persisted consent and rejection bound to the exact plan.
- Connect trusted host observations and show stale or missing evidence clearly.
- Re-check the displayed plan before submission and show differences on change.
- Test the default application flow, including rejection and changed-plan cases.

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
