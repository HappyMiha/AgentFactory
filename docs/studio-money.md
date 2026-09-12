# What it costs, what it would cost, and what to do when a tool costs money

Requirement trace: `AF-ST-801` (epic `AF-ST-E8`) and `AF-ST-901` (epic
`AF-ST-E9`). Neither is labelled accepted here.

## Three numbers, three rules

**Spent** is what a provider reported. It is gone; no stop recovers it.

**Reserved** is an estimate for work committed but not yet billed. A stop
releases it, so calling it spent would overstate the loss. A reservation stops
counting the moment its task is billed — the estimate stays in the ledger as
what was expected, and the reported cost is what is owed. Counting both would
double the money.

**The forecast** is arithmetic on measured tasks of this very mission: at least
three of them, or it says it does not know and why. A configured expectation is
never a measurement, and neither is a task that cost nothing.

Spend is attributed to the role, provider and model that incurred it, where
that was recorded. Spend with no role is shown as `unattributed` rather than
spread across the roles to make the table look complete.

## The limit belongs to a person

A limit is set by a named person, and raising it supersedes the old one without
erasing it, so the history shows who raised it and why. A reservation counts
towards the limit, which is how a run is stopped before the money is gone
rather than after.

Going over is a question, never a decision this module makes: `check()` returns
the same `over_budget` question the studio's autonomy rules use, with the cost
of the next step, what is left, and the two answers — raise the limit, or stop.

```bash
lokvetia studio limit --mission cat-coins --amount 5 --actor miha
lokvetia studio cost  --mission cat-coins --remaining-tasks 8 --language en   # exit 3 if over
```

## A paid tool is a choice, not a dead end

When work needs Unity, a paid asset pack or a paid service, the task does not
end the game. It becomes a choice with four ways out — use my own subscription
and sign in myself, buy it through the platform, take the free alternative, or
decline — and the free alternative is offered only when there actually is one
to name.

**Declining is a real answer.** It records the constraint and names exactly what
leaves the plan, so the person sees the price of their decision now instead of
finding a game that quietly lacks something later. `cut()` lists everything the
plan no longer contains for that reason.

**An unanswered choice holds up only what it is about.** Everything else keeps
moving.

**Credentials are the person's own.** This module has nowhere to put a licence
key, a password or a token — a test asserts the table has no such column — and
every rendering of a choice repeats that the login is entered by the person, in
that tool.

```bash
lokvetia studio paid-tools --mission cat-coins --language en   # exit 3 while one is open
lokvetia studio choose --choice 1 --way decline --actor miha
```

Over HTTP: `GET /api/studio/cost/{mission}` and
`GET /api/studio/paid-tools/{mission}` to read;
`POST /api/studio/cost/{mission}/limit`, `POST /api/studio/paid-tools/{mission}`
and `POST /api/studio/paid-tools/choices/{id}` to change, each behind the
explicit confirmation header.

## What is not claimed

- **Nothing here stops a worker or replans.** The limit produces the question;
  acting on the answer is the pipeline's job, and rebuilding the plan without a
  declined tool is the planner's.
- **Costs are recorded by whoever incurs them.** This module does not read a
  provider's invoice; it stores what the caller reports and refuses to invent
  the rest.
- **No screen yet.** API and command line.
