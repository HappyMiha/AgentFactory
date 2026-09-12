# Support levels, and what the evidence lets us say

"Almost any complexity" is a sales line, not a capability. This catalogue
replaces it with three declared levels and one rule: a level is **supported**
only after a real reference project passed every one of its acceptance criteria
and a named person reviewed the gameplay.

Requirement trace: `AF-GC-036`.

## The levels

| Level | Dimension | Features | Budget | Target |
|---|---|---|---|---|
| `simple-2d` | 2D | input, UI | handheld | 60 fps at 1152×648, load ≤ 3 s |
| `multi-level-2d` | 2D | input, UI, audio, save/load, multiple levels | low-end-laptop | 60 fps at 1920×1080, load ≤ 5 s |
| `small-3d` | 3D | input, UI, audio, save/load, 3D | baseline-pc | 60 fps at 1920×1080, load ≤ 10 s |

Each level declares the engine versions it was measured on, an asset budget
profile from [asset provenance](asset-provenance.md), a performance target, and
its acceptance criteria — a playable round, a reachable win *and* lose, restart,
a headless build, assets inside budget, and, where the level claims them,
progression, saved progress and audio.

## Separate investigations

Multiplayer, open world, console and VR are **not** levels and no level absorbs
them. Each carries a stated reason — netcode and abuse handling are a product of
their own, streaming changes every other requirement, console needs a partner
agreement, VR has comfort and performance requirements nothing here measures. A
request that touches one gets it split out, named, and excluded from the build.

## Evidence

```json
{"evidence": [{
  "level_id": "simple-2d",
  "reference_project": "reference/collector",
  "version_digest": "<playable version digest>",
  "checks": {"playable_round": true, "win_lose": true, "restart": true,
             "headless_build": true, "budget": true},
  "gameplay_reviewer": "the person who played it"
}]}
```

Evidence must name the project, the exact version it came from, and the person
who played it — a run nobody reviewed does not verify a level. Evidence that
refers to a criterion the level does not declare is refused, so a level cannot
be verified against invented tests. Several projects may cover a level between
them; one later failing check drops it back to `partial`.

`examples/capability-evidence.json` ships **empty**, on purpose: every level
starts `proposed`, which is the truthful state until someone runs one.

## Answering "can you build this?"

`scope` returns one of four outcomes and a plain statement to show a creator:

| Outcome | When | `guarantee` |
|---|---|---|
| `supported` | a level covers everything asked and is fully verified | `true` |
| `scoped_prototype` | the closest level covers part of it, or is not verified yet | `false` |
| `investigation` | everything asked is in an unresearched area | `false` |
| `unsupported` | no level covers that engine and dimension | `false` |

`guarantee` is `true` in exactly one case, and a test asserts that across a
matrix of requests. A scoped prototype always names what was dropped and why it
is an attempt rather than a promise.

```bash
lokvetia levels list
lokvetia levels show  --level simple-2d --evidence ./examples/capability-evidence.json
lokvetia levels scope --feature input --feature ui --feature save_load
lokvetia levels scope --feature input --feature multiplayer
```

`levels scope` and `levels show` exit `3` unless the answer is a real guarantee,
so a caller cannot read a prototype as a promise.

## What this does not do

It does not measure anything by itself. It records what a real run proved, and
refuses to say more than that. Running the reference-game benchmark — playability,
performance and build regression at each level, plus the manual gameplay review —
is the acceptance work for `AF-GC-036`, and none of it is recorded yet.
