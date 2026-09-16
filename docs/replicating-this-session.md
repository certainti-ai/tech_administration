# Replicating this session

How to stand up another Claude Code session that can query the production
databases the way this one does — **reusing the existing maintenance VM and Key
Vault**. Nothing here creates a VM, a vault, or a database credential.

## The shape of it

```
Claude Code session                Azure control plane          trd365-maint-vm
(no route to your estate)  --POST runCommand-->  management.azure.com  -->  guest
                                                                            agent
                                                                             |
                                          Key Vault <-- managed identity ----+
                                     trd365-maint-kv-9qgdg5                  |
                                                                             |
                             bastion <-- SSH tunnel -------------------------+
                       172.203.151.166                                       |
                             |                                               |
                    private-endpoint Postgres <-- psycopg2 over 127.0.0.1 ----+
```

The session never opens a socket to the estate. It asks Azure to run a script;
the VM's guest agent collects and runs it; the VM resolves credentials from the
vault and opens the tunnel. **No database password belongs in the session.**

## What already exists — do not recreate any of it

| Thing | Value |
|---|---|
| Maintenance VM | `trd365-maint-vm`, resource group `trd365-maintenance`, centralus |
| Key Vault | `trd365-maint-kv-9qgdg5`, RBAC-authorised, holds all 40 credential secrets |
| VM identity | user-assigned, holds **Key Vault Secrets User** on that vault |
| VM config | `/etc/trd365/environment` carries `AZURE_KEY_VAULT_NAME` and `AZURE_CLIENT_ID` — no secrets |
| Runtime | `/opt/trd365/venv` with `trd365-core` installed, service account `trd365` |

## Step 1 — decide the identity

The session authenticates to Azure as a service principal. Either reuse the
existing one, or register a fresh one to keep the two sessions distinguishable
in the Activity Log. A fresh one is the better habit; reusing is fine for a
short-lived investigation.

The principal needs **exactly one** capability —
`Microsoft.Compute/virtualMachines/runCommand/action` — which the built-in
**Virtual Machine Contributor** role contains. Scope it to the **VM resource**,
not the subscription and not the resource group:

```
/subscriptions/<SUB>/resourceGroups/trd365-maintenance
  /providers/Microsoft.Compute/virtualMachines/trd365-maint-vm
```

Do **not** grant it Key Vault access. Do **not** grant it any database role.
The VM reads the vault with its own identity; the session never needs to.

## Step 2 — create the Claude Code environment

In claude.ai -> Code -> Environments -> new environment:

1. **Source**: the `certainti-ai/tech_administration` repository.
2. **Environment variables — these six, and nothing else:**

   | Variable | Value |
   |---|---|
   | `ARM_TENANT_ID` | the directory the principal lives in |
   | `ARM_CLIENT_ID` | the principal's application id |
   | `ARM_CLIENT_SECRET` | the principal's secret |
   | `ARM_SUBSCRIPTION_ID` | the subscription holding the VM |
   | `TRD365_RG` | `trd365-maintenance` |
   | `TRD365_VM` | `trd365-maint-vm` |

3. **Network policy**: outbound HTTPS to `login.microsoftonline.com` and
   `management.azure.com`. Nothing else is required — not the databases, not the
   bastion, not the vault.

### The mistake to avoid

Do **not** add `MAINDB_PASSWORD`, `ORGDB_PASSWORD`, `TRD365AI_PASSWORD`,
`MAINDB_SSH_PASSWORD`, `ORGDB_SSH_PASSWORD`, or any `TRD365_<ENV>_*` variable.

Every one of those values is already in `trd365-maint-kv-9qgdg5`, and
`environments.py::_lookup` reads **the environment before the vault** — so
setting them does not help the VM, it *overrides* the vault, and it puts
production database and bastion passwords inside a session container that has
no need for them. This is the one thing the current environment gets wrong.

## Step 3 — confirm the VM side is healthy

From the new session:

```bash
python tools/run_on_vm.py 'hostname; cat /etc/trd365/environment'
python tools/run_on_vm.py 'sudo /opt/trd365/verify.sh'
```

`verify.sh` proves the VM can open each tunnel and reach each database. If it
passes, the session is ready; if it fails, the problem is on the VM or in the
vault, not in the session.

## Step 4 — run a query

```bash
python tools/run_on_vm.py - <<'SH'
set -a; . /etc/trd365/environment; set +a
sudo -E -u trd365 /opt/trd365/venv/bin/python - <<'PY'
from trd365_core.environments import Environment
from trd365_core.db import ConnectionPool
with ConnectionPool(Environment.PROD) as pool:
    print(pool.fetch("maindb", "SELECT count(*) FROM trd365.account"))
PY
SH
```

The `[tunnel] maindb: 127.0.0.1:<port> -> ...` line in the output is the SSH
forward opening. `Environment.STAGE` and the rest work the same way.

## Step 5 — know the three limits

They shape how everything is written, and each one cost real time to discover.

1. **Stdout is capped at about 4,095 characters per call.** Anything bigger —
   a catalogue, a row export — gets gzipped and base64'd on the VM, then read
   back in slices. `tools/run_on_vm.py --fetch` does that.
2. **One run-command at a time per VM.** A second returns HTTP 409. The tool
   waits and retries rather than failing.
3. **Long polls get dropped** by the proxy in front of a session host. The
   script keeps running on the VM regardless — the tool tolerates the drop and
   keeps polling. Never resubmit on a dropped poll; check for the output file.

## Step 6 — give the session its rules

Point the new session at `docs/standing-rules.md`. The read-only discipline,
the approval requirements and the deliverable constraints are all there, and a
session that reaches production should inherit them deliberately rather than by
luck.

## Revoking access

Removing the principal's role assignment on the VM ends it immediately, with no
effect on the VM, the vault, or any other session.
