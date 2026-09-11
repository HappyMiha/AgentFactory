# Support bundles you can read before you send them

Asking an owner for diagnostics is asking them to trust you with their machine.
This tool is built so that trust is not required: nothing optional is collected
unless it was named, the selection has a preview that can be read in full, every
collected value passes the same redaction rules the export gate refuses on, and
some things have no collector at all.

Requirement trace: the diagnostics half of `AF-GC-038`. The signed update with
backup, migration and rollback, and the uninstall boundary between the
application and user games, are **not** in this change; that item stays open.

## What is collected

| Category | Collected |
|---|---|
| `versions` | always — core, Python, platform, schema version, installed packs |
| `environment` | on request — variable **names only** |
| `configuration` | on request — the shipped defaults |
| `audit_events` | on request — event type, entity and time, never the payload |
| `logs` | on request |
| `prompts` | on request |
| `game_files` | on request |

Credentials, provider auth profiles, private keys and session tokens have **no
collector**, so no selection can include them. Environment variables contribute
their names and a `looks_sensitive` flag; a variable's value is never read into
the bundle.

## Preview, then package

`preview` returns every item with its size and the redaction rules that were
applied, plus the categories that were *not* selected and the ones that are
never collected. `preview --show <name>` prints one item's exact text — the
bytes that would be sent, after redaction.

`bundle` re-collects and refuses if the diagnostics changed since the preview
was read, so what is packaged is what was reviewed. It records who assembled it,
and the package carries a `READ-BEFORE-SENDING.md` that repeats what was left
out and which redactions ran.

Redaction keeps the surrounding text: a log line with an AWS key becomes
`... [redacted: aws access key] ...`, so the line is still diagnostic. Export
refuses a package that contains a secret and support redacts it — both use the
same rules, so a value one refuses is never a value the other ships in the
clear.

```bash
lokvetia support categories
lokvetia support preview --include logs
lokvetia support preview --include logs --show worker.log
lokvetia support bundle --include logs --output ./support.zip --actor "your-name"
```

## What this does not do

It does not decide what is wrong, upload anything anywhere, or guarantee that a
redaction rule catches every secret shape. It collects a named, reviewable set,
redacts what it recognises, and leaves the sending to a person.
