# Development progress page

The gateway serves `/progress` on both test domains to signed-in operators. The
page reads `/progress/status`, which the deployment controller republishes each
cycle from the bare clones it already fetches. No repository is written to, and
no GitHub token reaches the browser.

## Three tracks that never merge into one number

| Track | Source | What it proves |
|---|---|---|
| Evidence recorded | `evidence` entries on the backlog item | Somebody named what was produced and where to find it |
| Mentioned in main | A task identifier observed in a commit subject | The ID was mentioned; neither implementation nor completion is established |
| Accepted | `status:accepted` in the backlog manifest | Owner acceptance against the task's release gate |

A merge never sets acceptance, and recorded evidence is not a verdict — a
reviewer still has to read what it names. The page reports the three tracks
separately at task, block, project, and total level. A published percentage
describes coverage of a planning baseline. It is not a statement that a build
runs, a game plays, or a service is deployed.

The API retains the field name `merged` for the history-reference track. This track only sees identifiers that a commit message cites. Work
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

`accepted` (manifest label) wins, then `in_progress`, then `blocked` (a declared label or a dependency without recorded acceptance), then `merged` (a commit references the exact identifier), then `todo`. A commit mention never clears a dependency. Cross-product dependencies use qualified `core:` and `cloud:` identifiers; a missing prerequisite remains blocked.
Identifiers match on token boundaries only, so `AF-CLD-001` is never credited
with work described by `AF-CLD-0012`.

`ready` lists unstarted tasks with no unaccepted hard dependencies in the loaded manifests. It does not certify release ordering, reuse receipts, environment qualification, or permission to execute. `remaining` counts all tasks not accepted, whether or not commits mention them.

## Large blocks

Tasks group by their declared `milestone:` label, then by their topmost epic,
then by a `release:` label. Every block key carries its manifest, so one
manifest's M0 is never merged into another manifest's M0.

## Percentages

A percentage is weighted by the `size:` label — S=2, M=5, L=10 relative planning
units, and 5 for an unsized task — so a milestone of large tasks cannot look
complete because several small tasks were referenced. Counts are published alongside the
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


## Portfolio coverage and failure handling

The default configuration includes all 280 executable requirements: 183 in Core
(including 35 RSI cards) and 97 in Lokiravia (including 30 living-world cards).
`docs/evolution/backlog.json` is read through a reporting adapter; its design-only
schema is never turned into an executable runtime import. The implementation
order and release gates remain in the bilingual evolution portfolio.

Any missing or invalid configured manifest fails the refresh and preserves the
previous report, including its original timestamp. This prevents a partial read
from silently shrinking the denominator. An operator who overrides the manifest
list deliberately sees only that configured scope. Historical commit references
are bounded and may include planning-only or reverted work.
