# Godot 2D game pack and engine adapter

Core stays engine-neutral. This pack owns the Godot-specific payload — the
supported engine range, two starter templates, and the adapter that runs the
real engine — so the orchestration layer never learns about GDScript.

Requirement trace: `AF-GC-016` (pack and templates) and `AF-GC-017` (validated
project and real build). Merging this work is engineering delivery, not product
acceptance: the acceptance gates below still need a real engine on a real
machine.

## What the pack ships

| Template | Round | Win | Lose |
|---|---|---|---|
| `collector-2d` | Open field, six markers, 30-second clock | every marker collected | the clock runs out |
| `platformer-2d` | Four platforms and a goal marker | the goal is reached | the player falls off the map |

Both templates:

- pin Godot **4.3** (4.3 and 4.4 are the supported series) and the
  `gl_compatibility` renderer, so a baseline PC without a modern GPU still runs
  the project;
- use GDScript and the `scenes/`, `scripts/` layout with `project.godot`,
  `export_presets.cfg` and a `README.md`;
- bind movement, jump and restart to the built-in `ui_*` actions, so no input
  map has to be shipped or merged;
- contain **no external content**: every visual is a `ColorRect` built by the
  project itself, so there is no third-party asset licence to clear.

## Preview before write

A template is materialised in two steps. `plan` reads the project, compares
every pack-owned file against the digest recorded at the last install, and
classifies it:

| Action | Meaning |
|---|---|
| `create` | the file is absent |
| `keep` | already identical, or a creator-owned file such as `README.md` |
| `update` | pack-owned and unmodified since the last install |
| `conflict` | **you edited it** — the pack will not touch it |

`apply` writes only what the reviewed plan declared. It refuses the whole
operation when a conflict is unapproved, and an approved overwrite needs the
exact file path *and* a named human approver. If the project changed between
plan and apply, the apply is refused rather than silently re-planned.

```bash
lokvetia godot templates
lokvetia godot plan  --template collector-2d --path ./my-game
lokvetia godot apply --template collector-2d --path ./my-game

# after you have edited scripts/main.gd yourself
lokvetia godot apply --template collector-2d --path ./my-game \
    --approve-overwrite scripts/main.gd --actor "your-name"
```

`.lokvetia/godot-pack.json` records the pack version, template digest, and the
digest of every file at install time. That record is what makes "you edited
this" distinguishable from "the pack shipped a new version".

## Running the real engine

`GodotAdapter` executes a fixed set of operations with no shell, a hard
timeout, and a bounded log. Each run is recorded with its own evidence kind:

| Operation | Command | Evidence kind |
|---|---|---|
| `health` | `--version`, `--help` | engine identity and interface qualification |
| `import` | `--headless --path P --import` | `engine_import` |
| `script_check` | `--headless --path P --check-only --script res://…` | `static_script_check` |
| `headless_smoke` | `--headless --path P --quit-after N` | `headless_runtime` |
| `export` | `--headless --path P --export-release PRESET OUT` | `engine_export` |

Rules that keep the verdict honest:

- **Exit code 0 is not enough.** Output is scanned for `SCRIPT ERROR`, parse
  errors, missing export templates, missing resources and crash markers; any of
  them fails the run even when the engine exits cleanly.
- **`--check-only` is never a game test.** It is recorded as
  `static_script_check`, and a successful build still reports
  `graphical_playtest` in its `evidence_gap`.
- **An unsupported engine series never starts a build.** `3.x` is refused at
  the health gate.
- **A preset that the project does not declare never launches the engine.**
  `export_presets.cfg` is read first and the failure names the declared presets.
- **A successful export with no artifact file on disk is a failure.**

```bash
lokvetia godot health
lokvetia godot build --template collector-2d --path ./my-game \
    --preset linux-x86_64 --output ./build/linux/collector.x86_64 \
    --commit "$(git rev-parse HEAD)"
```

The build returns an artifact record: project digest, source commit, engine
version, template id and version, preset, artifact path, SHA-256 checksum and
size, plus every run with its exit code, duration and command digest.

## What is still missing for acceptance

| Gate | Status |
|---|---|
| Unit qualification against a stand-in engine CLI | done in `tests/test_godot_engine.py` |
| Both templates opened and played in a real Godot editor | **not done** |
| Export with real export templates installed, on Linux and Windows | **not done** |
| Graphical (non-headless) playtest | **not done** |

Until those three rows are filled in with recorded evidence, `AF-GC-016` and
`AF-GC-017` stay open.
