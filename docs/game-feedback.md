# "Make the jump higher"

That sentence is the whole interface a twelve-year-old should need after
playing their game. Four things must not happen behind it, and this is how each
one is prevented.

Requirement trace: `AF-GC-022`. The backlog item is not labelled accepted here;
what is and is not covered is at the bottom of this page.

## 1. Nothing leaves the machine unseen

A note is bound to the build that was actually played, and
`Feedback.preview()` returns exactly what would be sent: the words verbatim,
the reproduction steps, every attachment by name and size, and a sentence
naming the attachments that would reach a cloud provider — or saying plainly
that nothing leaves this computer.

`POST /api/games/{project}/feedback/preview` and `lokvetia feedback preview`
return that preview and store nothing. Recording is a separate call.

## 2. Cost and scope are never accepted silently

A change plan states what would be done, what it disturbs among the
requirements already agreed, and what it costs. `needs_acceptance()` lists what
a person must say yes to, and `accept_plan` refuses without it:

```python
accept_plan(plan, actor="miha")                    # FeedbackRefused: adds cost
accept_plan(plan, actor="miha", accept_cost=True)  # accepted, and recorded as miha's
```

Accepting the cost is not accepting new scope; each is its own yes. An
unnamed person cannot accept anything. The acceptance endpoint rebuilds the
plan from what is stored rather than from the request, so a request cannot
declare a plan free and then be accepted as free.

A plan built on a newer version than the one that was played says so, with both
version digests, instead of quietly applying the wish somewhere else.

## 3. A build that passed is not evidence that the wish came true

`judge()` looks only at checks that name this wish and actually ran:

| What happened | Verdict |
| --- | --- |
| No check names this wish | `not_checked` — "a build that succeeded is not evidence" |
| A check names it but never ran | `not_checked` |
| It passed, with no evidence recorded | `not_checked` — "there is a check but no evidence" |
| Any check for this wish failed | `fails` |
| Every check for it ran, passed and carries evidence | `holds` |

The verdict always carries the previous version, so going back is offered
whatever the answer.

## 4. The record cannot be rewritten afterwards

Migration 80 adds `game_feedback`, `game_feedback_plans` and
`game_feedback_checks`. Notes and checks cannot be updated or deleted, and a
plan may gain exactly one thing after it is written — its acceptance. Anything
else is refused by a trigger, because a record of what a person asked for is
worth nothing if it can be edited later to match what was delivered.

The same words about the same build are the same note, not a new one.

## From the command line

```bash
lokvetia feedback preview --project collector --version <digest> --wish "..." --send-file shot.png
lokvetia feedback add     --project collector --version <digest> --wish "..."
lokvetia feedback show    --id 3 --language en
lokvetia feedback accept  --plan 1 --actor miha --accept-cost
lokvetia feedback history --project collector
```

## What is not claimed

- **No planner.** This module does not turn a wish into a change plan; it
  records the plan whoever proposed it wrote, and enforces how it may be
  accepted. Wiring a planner to it is separate work.
- **No screen yet.** The flow is reachable over the API and the command line.
- **Going back** is the existing playable-version restore, which adds a new
  version pointing at the old one rather than rewriting history. This module
  reports that it is available; it does not perform it.
