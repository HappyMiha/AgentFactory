# Development progress page

The gateway serves `/progress` on both test domains to signed-in operators. The
page reads `/progress/status`, which the deployment controller republishes each
cycle from the bare clones it already fetches. No repository is written to, and
no GitHub token reaches the browser.

## Two tracks that never merge into one number

| Track | Source | What it proves |
|---|---|---|
| Code in main | A task identifier observed in the repository's own commit history | Engineering delivery of that change |
| Accepted | `status:accepted` in the backlog manifest | Owner acceptance against the task's release gate |

A merge never sets acceptance. Acceptance is declared in the manifest, and the
page reports the two tracks separately at task, block, project, and total level.
A published percentage describes coverage of a planning baseline. It is not a
statement that a build runs, a game plays, or a service is deployed.

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
`status:accepted` in the same reviewed change that records its evidence. Marking
a task accepted because its code merged defeats the separation this page exists
to show.
