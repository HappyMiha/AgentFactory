# Play it, say what you want, continue

The loop a person actually uses is: watch, play, notice something, pause, say it
in their own words, continue. Two rules make that loop worth trusting — a stage
never ends in silence, and what was asked for cannot be edited later to match
what was delivered.

Requirement trace: `AF-ST-501` (epic `AF-ST-E5`) and `AF-ST-601` (epic
`AF-ST-E6`). Neither is labelled accepted here.

## A stage ends in one of exactly two ways

**Playable.** A slice, backed by a version that is actually in the playable
ledger and whose evidence has no gap. A build nobody could run is not a slice,
so `playable()` refuses a version that does not exist, and refuses one whose
`evidence_gap` is non-empty — naming the gap.

**Nothing to test.** Said out loud, with the reason. The reason is a `Message`,
which cannot exist empty or in one language only, so this branch always arrives
with something to read.

Declarations are kept rather than overwritten. A later slice supersedes an
earlier one for the same stage, and both stay in the record, because the history
of what was playable when is part of what makes the claim checkable. A database
trigger enforces that, and the table itself refuses a `playable` row with no
version digest.

The plan screen reads the same map: a stage shows a Play button only where a
boundary says it is playable.

```bash
lokvetia studio slice  --mission cat-coins --stage base --project collector --version <digest>
lokvetia studio slice  --mission cat-coins --stage setup --nothing-uk "Лише підготовка." --nothing-en "Only preparation."
lokvetia studio slices --mission cat-coins --language en
```

## Pause stops the issuing of new tasks, not the world

Pressing pause does not freeze work already running, and the pause says so:
it lists what is still finishing, or states that nothing is running. Pausing a
paused mission is refused rather than silently ignored, and both a pause and a
continue are recorded against a named person.

A comment is kept in the person's own words, tied to the cycle that was open
when they wrote it, and scoped to the game, a stage, or one task. Comments
cannot be updated or deleted: what a person asked for is evidence, and editing
it later would turn the history of a game into a story about it.

Continuing closes the cycle, opens the next one, and hands over that cycle's
comments — with a note saying plainly that until the planner replans, those
comments are not in the backlog yet. The history answers "did my double jump get
planned?" with a fact: which comments belong to which cycle, who paused, who
continued, and when.

```bash
lokvetia studio pause   --mission cat-coins --actor miha --finishing "level build"
lokvetia studio comment --mission cat-coins --text "хочу подвійний стрибок"
lokvetia studio resume  --mission cat-coins --actor miha
lokvetia studio cycles  --mission cat-coins --language en
```

Over HTTP: `GET /api/studio/slices/{mission}` and
`GET /api/studio/cycles/{mission}` to read; `POST` to
`/api/studio/slices/{mission}/{stage}`, `/api/studio/cycles/{mission}/pause`,
`/comments` and `/resume` to change, each behind the same explicit confirmation
header as every other guarded change.

## What is not claimed

- **Nothing here replans.** Continuing hands the comments to whoever plans, and
  says so; it does not turn a sentence into tasks, and it never claims the
  comments were understood.
- **Nothing here stops a worker.** Pause records that no new task should be
  handed out; the caller lists what is still in flight, and stopping a running
  call is the separate, honest business of the stop plan.
- **Nothing here builds.** A slice is declared from a build that already exists
  in the playable ledger.
