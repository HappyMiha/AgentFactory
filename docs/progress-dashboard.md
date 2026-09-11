# Development progress page

The gateway serves `/progress` on both test domains to signed-in operators. The
page reads `/progress/status`, which the deployment controller republishes each
cycle from the bare clones it already fetches. No repository is written to, and
no GitHub token reaches the browser.

## Three tracks that never merge into one number

| Track | Source | What it proves |
|---|---|---|
| Evidence recorded | `evidence` entries on the backlog item | Somebody named what was produced and where to find it |
| Code in main | A task identifier observed in the repository's own commit history | Engineering delivery of that change |
| Accepted | `status:accepted` in the backlog manifest | Owner acceptance against the task's release gate |

A merge never sets acceptance, and recorded evidence is not a verdict — a
reviewer still has to read what it names. The page reports the three tracks
separately at task, block, project, and total level. A published percentage
describes coverage of a planning baseline. It is not a statement that a build
runs, a game plays, or a service is deployed.

The merged track only sees identifiers that a commit message cites. Work
delivered without citing its task reads as outstanding there, which is exactly
what the evidence track is for: record the files that prove it and the task
stops looking untouched.

## Recording evidence

An item may carry up to twenty entries. Each names a `kind` — `code`, `test`,
`document`, `run`, `review` or `deployment` — a `reference`, whoever recorded
it, and an optional short note:

```json
{"stable_id": "AF-GC-042", "evidence": [
  {"kind": "test", "reference": "tests/test_provider_role_qualification.py",
   "recorded_by": "Reviewer", "note": "profile by role matrix"},
  {"kind": "document", "reference": "docs/provider-role-qualification.md",
   "recorded_by": "Reviewer"}
]}
```

Unknown fields and invented kinds are refused rather than ignored, and the same
reference cannot be recorded twice on one item.

**An item marked `status:accepted` must name at least one entry.** Both the
canonical loader and `scripts/validate_backlog.py` refuse a manifest that
declares acceptance with nothing recorded, so the two cannot drift apart. This
gate checks that evidence exists, not that it is sufficient; judging that is the
reviewer's job.

## How a task is classified

`accepted` (manifest label) wins, then `merged` (a commit references the exact
identifier), then `in_progress` (manifest label), then `blocked` (a declared
label, or a dependency that is neither accepted nor merged), then `todo`.
Identifiers match on token boundaries only, so `AF-CLD-001` is never credited
with work described by `AF-CLD-0012`.

`ready` lists tasks that nothing blocks and nobody has started.

## Large blocks

Tasks group by their declared `milestone:` label, then by their topmost epic,
then by a `release:` label. Every block key carries its manifest, so one
manifest's M0 is never merged into another manifest's M0.

## Percentages

A percentage is weighted by the `size:` label — S=2, M=5, L=10 nominal engineer
days, and 5 for an unsized task — so a milestone of large tasks cannot look
complete because several small ones merged. Counts are published alongside the
weighted figure; the page shows both.

## Generating the report

```sh
python scripts/progress_report.py --config <config.json> --output <progress.json>
```

The configuration lists projects and the manifests to read from each one:

```json
{"projects": [
  {"id": "core", "name": "Lokvetia Core", "repository": "HappyMiha/Lokvetia-Core",
   "repo_path": "/state/repositories/Lokvetia-Core", "ref": "refs/heads/main",
   "manifests": ["examples/development-backlog.json"]}
]}
```

Only `HappyMiha/Lokvetia-Core` and `HappyMiha/Lokiravia` are accepted. A
repository path may be a bare clone or a working tree; manifests are read from
the named ref, never from an uncommitted file.

The controller runs this itself and writes `public/progress.json`. Adding
`"progress": {"projects": []}` to the controller configuration turns the
published report off; an existing configuration file without a `progress`
section uses the documented default. A failed run leaves the previous report on
screen rather than blanking the page.

## Keeping the acceptance track honest

The manifest is the only place acceptance is recorded, so a task moves to
`status:accepted` in the same reviewed change that records its evidence — the
loader now requires it. Marking a task accepted because its code merged defeats
the separation this page exists to show.
