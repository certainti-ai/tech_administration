# Python packages

## Built

| Package | Purpose |
|---|---|
| [`trd365-core`](trd365-core/) | Shared foundation: environments, connections, **the application data model**, CLI conventions, audit, registry |

## Planned

```
trd365-data-purge/           account / case / interaction / project / project_fiscal
trd365-account-deletion/     kept alongside data-purge/account pending a decision
trd365-data-model-analysis/  schema analysis; feeds the dashboard's health metrics
trd365-reference-corrections/
trd365-rd-percent-update/    ported from JavaScript
trd365-sharepoint-migration/
trd365-orchestrator/         Phase 2
```

Every package depends on `trd365-core` and imports the data model from it rather
than re-deriving schema conventions — see `docs/HANDOFF.md` §4.

Refactor **out of** `../legacy/trd365_maintenance/`; leave that tree untouched so
the original stays available for comparison.

```bash
pip install -e "packages/trd365-core[dev]"
pytest packages/ -q
ruff check packages/
```
