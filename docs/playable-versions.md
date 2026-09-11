# The latest verified playable version

Unfinished work must never take away the version a player can already launch.
This ledger keeps one pointer per project — the version that is known to build,
parse, run and export — and only a fully verified build moves it.

Requirement trace: `AF-GC-020`. Engine-neutral: the ledger stores a build
record, and `CandidateBuild.from_artifact` adapts whatever an engine adapter
produced, so nothing here knows what Godot is.

## What a playable checkpoint holds

Source commit, project digest, engine and engine version, template id and
version, export preset, artifact path, SHA-256 checksum and size, every
verification run with its status, and the evidence the build does **not**
provide (`evidence_gap`, for example `graphical_playtest`).

## Rules the ledger enforces

| Rule | Behaviour |
|---|---|
| A failing build never becomes playable | any run that is not `succeeded`, a missing checksum, a zero-byte artifact, or an empty verification list is rejected |
| A rejection never moves the pointer | the previous verified version stays current, and the rejection is recorded with its reason |
| Promotion is atomic | version row, pointer move and promotion record commit together; an interruption leaves no partial version |
| Promotion is replay-safe | the same `command_id` returns the recorded outcome instead of promoting twice |
| A command id is not reusable | reusing one for a different build is refused rather than silently re-pointed |
| Re-offering the current version changes nothing | the outcome is `unchanged` and the sequence does not advance |
| History is append-only | `UPDATE` and `DELETE` on versions and promotions are refused by the database |
| A restore preserves the original | it records a **new** version that points at the one it restored, on a named branch |
| A restore is previewed first | the CLI prints the preview and applies it only with `--confirm`, and a preview that no longer matches is refused |
| Build identity is checked | the same engine, commit, project digest and preset producing a different artifact checksum is promoted but flagged `reproducible: false` |

The artifact itself can be re-checked before a launch: `verify_artifact`
compares the file on disk against the recorded size and checksum, so a deleted,
truncated or replaced artifact is caught before a player is sent to it.

## Using it

```bash
lokvetia godot build --template collector-2d --path ./my-game \
    --preset linux-x86_64 --output ./build/linux/collector.x86_64 \
    --commit "$(git rev-parse HEAD)" > build.json

lokvetia playable promote --project my-game --engine godot \
    --build build.json --command-id release-17 --actor "your-name"

lokvetia playable current --project my-game
lokvetia playable verify  --project my-game
lokvetia playable history --project my-game

# restore: preview, then confirm
lokvetia playable restore --project my-game --version <digest> --branch restore/v1
lokvetia playable restore --project my-game --version <digest> --branch restore/v1 \
    --confirm --command-id restore-3 --actor "your-name"
```

`promote` exits `3` when the build was rejected, so a delivery loop can branch
on the exit code without parsing the reason.

## What this does not claim

A promoted version means every recorded check passed. It does not mean the game
was played: `evidence_gap` carries that through from the build record, and a
headless run is not a graphical playtest. Product acceptance of the creator
journey stays with `AF-GC-021` and the Lokiravia gates.
