# Python packages

Empty. This is where Phase 1 lands — see [`../docs/HANDOFF.md`](../docs/HANDOFF.md) §4.

Planned layout:

```
trd365-core/                 shared config, db + tunnels, CLI conventions, audit, registry
trd365-data-purge/           account / case / interaction / project / project_fiscal
trd365-account-deletion/
trd365-data-model-analysis/
trd365-reference-corrections/
trd365-rd-percent-update/    ported from JavaScript
trd365-sharepoint-migration/
trd365-orchestrator/         Phase 2
```

Refactor **out of** `../legacy/trd365_maintenance/`; leave that tree untouched so
the original stays available for comparison.
