# Resume a local game idea

`core:AF-GC-007` adds a local start page at `/`. The existing control center is
available at `/operations`, including its confirmation dialogs and readiness
checks. Both routes use the same loopback authentication boundary. There is no
hosted account or tenant conversion in this feature.

On an empty page, **Створити гру** is the primary action. A start has five
navigation steps: idea, configured AI, preparation, creation status, and play.
Opening a step is navigation only. It never approves a plan, spends a budget,
invokes a model, or starts a workflow.

## Saving and resuming

The title, exact idea text, selected model, current step and validation error
are saved in the local Core database. Edits save after a short pause; **Зберегти**
provides an explicit retry. Wait for the saved status before closing the browser.
An unsaved edit is not a backup. The page warns when leaving with an unconfirmed
save; a network failure keeps the text visible.

Reloading the saved start, including after server restart, restores its step.
Previous steps remain accessible. Stable command IDs prevent an ambiguous save
response from creating another revision on retry. A newer version in another
tab causes a conflict, preserving local text. **Відкрити останню збережену версію**
loads the saved version and keeps the conflicting text in a separate copy area.
This copy lasts only for the current page; copy it elsewhere if needed.

The AI dropdown reads the effective workspace provider configuration. Listed
models satisfy the configured seven-role local capability contract; listing is
not evidence of installation, authentication or qualification. Missing or invalid
configuration leaves the idea editable. This page makes no inference requests.

**Зберегти чернетку проєкту** requires a separate confirmation. It freezes the
original idea and selected configuration and passes them to Core's authoritative
intake, creating a DRAFT mission. The initial source cannot then be edited through
this start page. The existing Core source/version workflow remains authoritative
for subsequent mission changes. An interrupted intake displays a persisted
recovery state and retries the same Core intake command. Local submissions use
a SQLite writer lock in a small database-adjacent `.local-games-lock` sidecar so
multiple processes cannot submit the same start concurrently. The OS releases
the lock after process termination. Back up the main database and its SQLite WAL
using the existing database backup procedure; the lock file contains no source.

## Existing projects and honest progress

The page lists saved starts and existing autonomous missions owned by the current
local operator. Legacy projects without an autonomous mission remain in the
operator panel. Existing missions show their actual phase, work-item counts and
the next preparation action. Project IDs and mission IDs are distinct.

Core does not yet publish a verified playable-version record for this page.
Consequently `latest_working` is null and Play stays unavailable. Execution
checkpoints, completed tasks and workflow runs are never substituted for a working
game. The future playable-artifact producer must supply verified version binding
before this UI can offer playback. This change does not claim generated-game or
age-12+ acceptance.

The preparation step reads the existing readiness endpoint and runs its bounded
check only on explicit request. A positive report requires live checks and a
valid expiry. Failed refreshes and expiry clear the positive status. It certifies
only the selected environment route, never game readiness or execution approval.

The Cloud GameBrief editor and first-playable scope/roadmap/budget planner are
separate accepted capabilities. This local Core start neither reimplements those
planners nor assumes a hosted identity handoff.

## Large lists and API

Saved starts, existing missions and immutable idea versions expose search and
pagination with a maximum of 200 results per request. The UI uses pages of 20.
The operator work list uses pages of 50, a title/description search, and dropdowns
populated from actual project/type/status/priority/assignee values. Projects in
the operator selector are loaded across all pages. Historical idea versions are
source snapshots, not playable releases.

Routes under `/api/games` provide configured models, starts, owner-bound mission
projections, save, confirmed submit and version history. Clients send a canonical
UUID `command_id` and exact `expected_revision` for mutations. Unknown fields,
invalid steps/versions, overlong text, malformed Unicode, foreign owners and
conflicting command reuse are rejected. Submit additionally requires literal
`confirmed: true` and `X-Agent-Factory-Confirm: true`. Authentication, origin,
host and write-scope checks run before validation or storage access. Responses
inherit the existing no-store policy. Migration 74 adds start/history/command
tables without rewriting existing missions or source records.

Validation includes actual SQLite and HTTP contracts, recovery after an interrupted
intake, concurrent submissions, exact source preservation, owner isolation,
immutable history, upgrade from migration 73, and lists over 200 records. Actual
Chromium journeys cover the empty/mobile page, server restart, previous steps,
existing mission navigation, conflicting tabs, response loss, history/work search,
and readiness expiry. Model inference and playable build evidence are outside
these synthetic-source checks.
