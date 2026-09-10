# Lokvetia Core: brand and compatibility

Effective 8 September 2026. **Lokvetia** is the family brand at [lokvetia.com](https://lokvetia.com). **Lokvetia Core**, formerly AgentFactory Core, is the independent Apache-2.0 orchestration foundation. **Lokiravia**, formerly AgentFactory Cloud, is the separate game creation product at [lokiravia.com](https://lokiravia.com), presented as *by Lokvetia*.

## What changes

The README, application identity, browser titles, favicons, API title, command help, operator guide and project metadata use the new brand. `lokvetia` and `lokvetia-temporal-worker` are the preferred installed commands. Each calls the same implementation as its existing counterpart.

The canonical repository names are `HappyMiha/Lokvetia-Core` and `HappyMiha/Lokiravia`. The repository rename follows the merge of compatibility changes in both repositories. Existing Git URLs and PR links redirect after the rename. Do not create new repositories under the retired names; doing so would remove those redirects.

## Compatibility contract

| Surface | Current contract | Reason |
| --- | --- | --- |
| Primary command | `lokvetia` | New product identity |
| Worker command | `lokvetia-temporal-worker` | Same Temporal implementation |
| Existing commands | `agent-factory`, `agent-factory-temporal-worker` remain supported | Existing automation keeps working |
| Python distribution | `agent-factory-orchestrator` | Existing pinned consumers remain installable |
| Python module/import | `agent_factory`, `python -m agent_factory` | No import migration required |
| Workspace and database | `.agent-factory`, existing SQLite paths and schema | Existing data is opened in place |
| Configuration | `AGENT_FACTORY_*` and existing settings | No credentials or environment migration |
| Runtime identities | Existing Temporal namespaces, queues, workflow IDs, cookies and keyring entries | Running work and sign-ins remain discoverable |
| Package dependency | Existing Core commit pin in Lokiravia | Rebranding does not silently upgrade runtime behavior |
| Historical files | Existing backlog/PDF filenames and dated evidence | Old references remain valid |

The old strings in these technical surfaces are deliberate compatibility identifiers, not competing product names. Distribution/module renames would require a separately versioned migration and published compatibility packages.

## Update an existing checkout

Update your branch from the current `main`, preserve unrelated work and rerun the relevant checks. Once both repository renames are complete, an optional local remote update is:

```sh
git remote set-url origin https://github.com/HappyMiha/Lokvetia-Core.git
python -m pip install -e ".[web]"
lokvetia --help
lokvetia --workspace . web --open
```

The old remote continues to redirect. Existing branches, task IDs and historical review evidence remain valid after the rename.

The existing installation work under `core:AF-GC-014` remains separate from this rebrand. Historical documents retain their recorded findings with a current-brand note.

## Product truth and domains

Core retains its existing alpha status and human approval boundaries. Lokiravia remains in early development; a local idea editor or prototype is not a verified hosted game pipeline. Brand domains do not imply hosting, game generation, commerce, support email accounts, or a production launch. DNS, deployment and mail configuration are separate operational work.

See the [visual identity](visual-identity.md) for artwork and usage.
