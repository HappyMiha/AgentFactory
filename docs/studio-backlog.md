# The plan, in the words of the person who asked for the game

The engineering view of a plan is right for engineers: stable identifiers,
weights, labels, and the careful difference between an identifier appearing in
a commit subject and work actually being accepted. None of that belongs on the
screen of someone who asked for a game about a cat collecting coins.

Requirement trace: `AF-ST-401` (epic `AF-ST-E4`), and the stage-boundary half of
`AF-ST-501`. Neither is labelled accepted here.

## Four words, not seven

A live mission tracks seven statuses. A person needs four, and gets them:

| The mission's status | What the person reads | Why |
| --- | --- | --- |
| `DONE` | Done | Accepted work, and only accepted work. |
| `RUNNING` | In progress | |
| `READY`, `PROPOSED` | Planned | |
| `STALE` | Planned, with a note that the plan moved | It is not a fifth word to learn. |
| `BLOCKED` | Blocked | |
| `FAILED` | Blocked, with a note that an attempt failed | Blocked is what it means for the reader: nothing is moving. |

The engineering view's `merged` flag means an identifier appeared in a commit
subject. That is progress, not completion, so it renders as **in progress**
with a note saying exactly that — never as done.

## What the rendering refuses

- **A title that still carries an internal code.** `AF-GC-024 Accessibility` is
  refused rather than displayed; `human_title()` strips the code when a caller
  translates a manifest, and what reaches the screen is a name.
- **A stage that calls itself playable with nothing to play.** A stage may only
  be `playable` with the version digest of a build that exists. Otherwise it
  says, out loud, that there is nothing to test here yet — silence at a stage
  boundary is the failure this rule exists to prevent.
- **An identifier leaking through the record.** The rendered stage carries a
  handle (`stage-1`) that means nothing outside that rendering, because an
  identifier in the record is an identifier that ends up on the screen. A test
  renders a whole plan and asserts no code of the form `AF-…` appears anywhere
  in it.

## What it shows

The whole plan, not only the current task: every stage with its title, its
tasks with their state, the role leading each one in words (`Developer`, not
`coding-worker-codex`), the counts per state, and one line for what happens
next — the task in progress, else the first planned one, else "everything
planned is done" or "waiting for something to be unblocked".

```bash
lokvetia studio plan --mission cat-coins --language en
```

Over HTTP: `GET /api/studio/plan/{mission_key}` — a read, like everything else
about looking at work in progress.

## What is not claimed

- **Nothing writes the plan here.** The rendering reads a mission's own backlog
  revision and shows it; planning, replanning and status changes stay where
  they are.
- **A stage becomes playable when a caller says which version came out of it.**
  Recording that link at the stage boundary is `AF-ST-501`, and until it exists
  every stage honestly reports that there is nothing to test.
- **No screen yet.** The API and the command line are here; the page belongs
  with the rest of the studio interface.
