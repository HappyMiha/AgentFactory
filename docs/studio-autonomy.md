# The checks stay, the clicking goes

A person who wants a game has no idea what a backlog revision is. Asking them
to approve one is not safety; it is a wall with an engineering word painted on
it. So every gate that used to wait for a click is answered by a written
policy, the answer is recorded with the policy that produced it, and three
things — and only three — still reach a person.

Requirement trace: `AF-ST-301` and `AF-ST-302` (epic `AF-ST-E3`). Neither is
labelled accepted here; what is and is not wired is at the bottom of this page.

## The five gates

| Gate | Who answers it | Why |
| --- | --- | --- |
| A change to the plan of work | policy | The plan is always visible, and can be edited while the work is paused. |
| Permission to run the work | policy | Granted when the mission starts, and written to the journal. |
| Readiness of the environment | policy | A failed check becomes a task to fix the environment, not a screen that stops everything. |
| Compatibility of the stored data | always automatic | It protects data that already exists, so it is never skipped and never asked about. |
| Evidence from the engine | evidence, never a person | A slice is not called playable without the engine actually running. Nobody can sign that on the engine's behalf. |

The last row is the one that looks like a gate and is not. It does not wait for
a person and it cannot be waved through: it waits for evidence.

## The three questions that remain

A person is asked when, and only when:

* **money would go over the limit** — the question carries the cost of the next
  step and what is left, and offers to raise the limit or stop;
* **an action cannot be undone** — publishing, deleting — and offers to do it or
  skip it;
* **the request is beyond what the product declares it can do** — the question
  quotes that declaration and offers an investigation with an unknown outcome,
  or a narrower task.

Anything else is decided and logged. A made-up fourth reason is refused by the
type, not by review.

## A question is not a wall

Each question records what it is about. `blocked_by_questions()` returns only
those subjects, so work that does not depend on the answer keeps going, and a
question nobody answers holds up nothing else. A question whose subject has
gone away is withdrawn rather than left waiting.

An answer must be one of the options offered, and is recorded against a named
person. A question is answered once: a second answer is refused, by a database
trigger as well as by the code.

## The journal

Migration 81 adds `studio_decisions` and `studio_questions`. A decision records
the gate, whether it was automatic, the summary and the policy in both
languages, and a digest of the context it was decided from. Decisions cannot be
updated or deleted — an automation whose log can be edited afterwards is not a
reason to trust the automation.

```bash
lokvetia studio gates --language en        # who answers each gate, and why
lokvetia studio decisions --mission m1     # what was decided; exit 3 if a question is open
lokvetia studio answer --question 4 --answer raise_limit --actor miha
```

Over HTTP: `GET /api/studio/gates`, `GET /api/studio/decisions`, and
`POST /api/studio/questions/{id}/answer`, which needs the same explicit
confirmation header as every other guarded change.

## What is not claimed

- **The existing approval services are not yet routed through this.**
  `autonomous_backlog_approval.py` and `autonomous_authorization.py` still hold
  their own transactions; this module decides and records, and wiring each call
  site to it is the rest of `AF-ST-301`.
- **No screen yet.** The gates, the journal and the questions are reachable over
  the API and the command line; putting the questions in the feed belongs with
  the backlog screen (`AF-ST-401`).
- **The cost limit is not read from settings here.** The caller passes the
  amount and the remainder; connecting that to the recorded budget is
  `AF-ST-801`.
