# Sanitized export — trd365_maintenance scripts

This is a scripts-only copy of the workspace, prepared for import into Claude Code.

## Secrets removed (replaced with `CHANGE_ME`)
- DB passwords (main / org / trd365ai) and `ssh_password` in every `config/db_config.json`
- SharePoint `client_secret` (source + dest) in `sharepoint_migration/config.json` and `config_globalfinance.json`
- DB + SSH passwords in `manual-rd-percent-update/db-config.js`

Fill these back in locally before running. Do not commit real values.

## NOT secrets, intentionally KEPT (so scripts stay self-documenting)
- DB hostnames, the SSH bastion IP (172.203.151.166), DB usernames (adminUser/aiadmin/thinkrd_DevOps)
- Azure `tenant_id` / `client_id` in the SharePoint configs (identifiers, not secrets)
If you want these stripped too, say so and they can be blanked.

## Excluded from this export (data / runtime output / deps)
- Customer data: all `*.csv` (Birlasoft / Infosys QRE financials), `manual-rd-percent-update/archive/`
- Runtime output: `reports/`, `state/`, `interactions_dashboard/site/`, `*.log`, `*.out`
- Dependencies / junk: `node_modules/`, `__pycache__/`, `.git/`, `.DS_Store`, `.claude/`
