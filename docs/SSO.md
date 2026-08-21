# Entra ID sign-in

How to put this application behind Microsoft sign-in for the certainti.ai tenant,
and how access is controlled once it is.

The code is written, tested and inert: with none of the `entra_*` Terraform
variables set, the deployment behaves exactly as it does today. Turning it on is
three things — a DNS record (§3), an app registration (§4), and a `terraform
apply` (§4, step 3).

Tenant: `b6734060-665c-4b7b-94e2-716458c1d933`.
Hostname: `tech-controlcentre.certainti.ai`.

---

## 1. Who gets in, and what they can do

**Access is an assignment, not a domain.** Having a `@certainti.ai` account grants
nothing. There are exactly four levels, and the default is the first:

| Level | How | What they can do |
|---|---|---|
| **No access** | Not assigned any app role | Cannot sign in. The application refuses the callback with a message naming what to ask for, and issues no session. |
| **Read only** | Assigned `viewer` | Read everything: environments, the utility catalogue, the data model, jobs, the audit trail. Cannot start anything that writes — and every utility writes. |
| **Update** | Assigned `operator` | Everything a viewer can do, plus start runs. Production writes still wait for a second person. |
| **Approve** | Assigned `approver` | Approve or reject somebody *else's* production run. Self-approval is refused regardless of what else they hold. |

`admin` exists and holds both `operator` and `approver`. Assign it sparingly: it
is the one combination that lets one person complete a production deletion alone.

Two of these are worth being precise about, because they are the reason the
shared password has to go:

* **"Update" is not "unlimited".** An operator can start anything, but a
  production run that writes is submitted as `pending_approval` and does not
  start. Nor can they approve it themselves. The same applies to a *preview* of
  `purge-project` or `purge-project-fiscal`, because those preview by executing
  the delete-and-recompute and rolling it back — same locks, same work.
* **"No access" is enforced twice.** Entra can refuse the sign-in before it
  reaches us (§4, "assignment required"), and the application refuses it again if
  it arrives anyway. Belt and braces, because the two are maintained by different
  people.

### Recommended assignment

Assign **groups**, not people, so joining and leaving a team is the only thing
anyone has to remember:

| Group | Role |
|---|---|
| Platform / DBA team | `operator` |
| Engineering leads who sign off deletions | `approver` |
| Support, analysts, anyone who needs to look | `viewer` |
| Everybody else | nothing — and so, no access |

---

## 2. How it works

The OpenID Connect authorization-code flow with PKCE, single tenant:

1. `/auth/login` → Microsoft, carrying `state`, `nonce` and a PKCE challenge, all
   three remembered in a short-lived signed cookie. No server-side state, so a
   restart mid-sign-in fails cleanly.
2. `/auth/callback` → checks `state`, exchanges the code, then **verifies the ID
   token's signature against the tenant's published keys** and checks issuer,
   audience, tenant and nonce.
3. The claims become a session in a signed, HttpOnly, Secure cookie holding only
   subject, name, roles and an expiry. **No access or refresh token is kept** —
   nothing here calls Graph, and a token not held cannot leak.

**Why the application verifies the token rather than trusting a proxy header.**
An authenticating proxy that injects `X-Auth-User` is less work and strictly
weaker: the application ends up believing a header, which is exactly what makes
the current development authenticator unfit for production. Here the trust
boundary is a signature, not a network path — so this replaces *both* temporary
measures at once, the shared Caddy password and the header authenticator.

Once Entra is configured the header authenticator is ignored even if
`TRD365_DEV_AUTH=1` is still set, and Caddy stops asking for a password and stops
injecting a role. A host with both cannot be signed into by naming your own roles.

---

## 3. DNS

One record, in GoDaddy, where `certainti.ai` is hosted (`pdns11.domaincontrol.com`
/ `pdns12.domaincontrol.com` — the `certainti.ai-dns` zone in Azure holds no A
records and does not serve the domain).

| Field | Value |
|---|---|
| Type | `A` |
| Name / Host | `tech-controlcentre` |
| Value / Points to | `52.173.109.182` |
| TTL | 600 seconds (10 minutes) — or the shortest offered |

An `A` record and not a `CNAME`: `CNAME` would need a name to point at, and the
VM has none — an Azure public IP only gets a `*.cloudapp.azure.com` label if one
is configured, and adding a layer whose only job is to be renamed later is not
worth it. The IP is a **Static** Standard address, so it survives deallocation
and reboots; it changes only if the public IP resource is destroyed and recreated.

Nothing else is needed. No `www`, no `TXT`, no CAA unless the domain already has
one — if it does, it must permit `letsencrypt.org` or the certificate cannot be
issued.

**Then TLS happens by itself.** Caddy asks Let's Encrypt for a certificate over
the HTTP-01 challenge, which needs inbound port 80 — already open, and already how
the current certificate was obtained.

Once the record resolves, point the running host at it:

```bash
# From this repo, against the live VM.
az vm run-command invoke -g trd365-maintenance -n trd365-maint-vm \
  --command-id RunShellScript \
  --scripts "/opt/trd365/app/infra/deploy/set-hostname.sh tech-controlcentre.certainti.ai"
```

That script refuses to do anything until the name resolves to this VM, because a
reload with a name that does not is a failed ACME challenge and Let's Encrypt
rate-limits those. Follow it with `terraform apply -var
public_hostname=tech-controlcentre.certainti.ai` so a future rebuild comes up with
the same name — `cloud-init` writes the Caddyfile only at first boot, which is
precisely why the script exists.

---

## 4. Turning sign-in on

Two routes. They produce the same thing; pick by who is doing it.

### Route A — `infra/entra`, as code

`infra/entra/` is a small Terraform root module that creates the registration, the
four roles, the "assignment required" switch, and both secrets — writing them
straight into the vault the VM reads. See its README. It needs directory rights,
so it is applied by a person, from their own machine, once:

```bash
cd infra/entra
terraform init
az login --tenant b6734060-665c-4b7b-94e2-716458c1d933

terraform apply \
  -var public_hostname=tech-controlcentre.certainti.ai \
  -var key_vault_name=trd365-maint-kv-9qgdg5
```

It prints the client id and what to do with it. Then assign somebody (§1), and
apply the VM deployment with the three variables in step 3 below.

**Who can run it:** *Application Administrator* (or Cloud Application
Administrator) to create the registration, plus *Key Vault Secrets Officer* on
`trd365-maint-kv-9qgdg5` to store the secrets. If you hold the first and not the
second, add `-var write_secrets_to_vault=false` and hand the two outputs to
somebody who does.

**If you would rather this ran unattended** — from the deployment service
principal `7b8767e1-1618-424a-a206-b66e892fc91e` rather than from a person — it
needs exactly one Microsoft Graph **application** permission, with admin consent:

| Permission | Type | Why this one |
|---|---|---|
| `Application.ReadWrite.OwnedBy` | Application | Create and manage app registrations **it owns** — enough for this module, and it cannot touch any other application in the tenant. |

That is the whole ask. Two permissions people commonly add alongside it are worth
declining:

* `Application.ReadWrite.All` — the same capability over *every* registration in
  the tenant, including ones that guard other systems. `OwnedBy` is the same job
  with a blast radius of one.
* `AppRoleAssignment.ReadWrite.All` — would let the module assign the groups in
  §1 too. It also lets its holder grant *any* app role of *any* application to
  *any* principal, which includes granting itself Graph roles. Deciding who can
  delete production data is a governance act with a human on the end of it; it
  should not be a Terraform variable. Leave the assignment lists empty and assign
  in the portal.

The module already assumes this: `app_role_assignment_required = true` means the
registration existing grants nobody anything until somebody is deliberately
assigned.

### Route B — the portal

Everything Route A does, by hand. In the Entra admin centre, certainti.ai tenant.

**1. Register the application.** Entra ID → App registrations → New registration.

* Name: `Certainti Tech Administration`
* Supported account types: **Accounts in this organizational directory only**
  (single tenant). Anything wider is a larger blast radius for no benefit; the
  application checks the `tid` claim and would refuse other tenants anyway.
* Redirect URI: **Web** → `https://tech-controlcentre.certainti.ai/auth/callback`

Note the **Application (client) ID**. The redirect URI must match what Caddy
serves exactly — Terraform derives it from `public_hostname` for that reason, and
a mismatch produces `AADSTS50011` with nothing on this side to explain it.

**2. Create a client secret.** Certificates & secrets → New client secret. Copy it
now; it is not shown again. A certificate is better if you would rather not rotate
a secret — say so and I will switch the code to one.

**3. Define the four app roles.** App roles → Create app role, four times. The
**value** is what the application reads and must be exactly:

| Display name | Value | Allowed member types |
|---|---|---|
| Viewer | `viewer` | Users/Groups |
| Operator | `operator` | Users/Groups |
| Approver | `approver` | Users/Groups |
| Administrator | `admin` | Users/Groups |

**4. Emit the roles.** Token configuration → the `roles` claim is included for app
roles automatically. Nothing to do unless you chose groups instead — see §6.

**5. Assign people.** Enterprise applications → Certainti Tech Administration →
Users and groups → Add user/group, choosing a role each time. Groups are better
than people.

**6. Require assignment.** Enterprise applications → the same app → Properties →
**Assignment required: Yes**.

This is the one that answers "I don't want everyone with a certainti.ai id to get
in". With it on, an unassigned person cannot complete sign-in at all — Entra stops
them with `AADSTS50105` before the application is involved.

**7. Put the two secrets in the vault.**

```bash
AZURE_KEY_VAULT_NAME=trd365-maint-kv-9qgdg5

az keyvault secret set --vault-name $AZURE_KEY_VAULT_NAME \
  --name entra-client-secret --value '<the secret from step 2>'

# Signs session cookies. Not a password anyone types; 32 random bytes.
az keyvault secret set --vault-name $AZURE_KEY_VAULT_NAME \
  --name session-signing-secret --value "$(openssl rand -base64 32)"
```

The VM reads both through its managed identity, so neither ends up in a unit file
or a process listing.

### Then, either way — turn it on

Two steps, and the order does not matter, but **both are needed**: one for the
host that is running now, one for the host that gets rebuilt later.

**The running host.** `/etc/trd365/environment` and the Caddyfile are written by
cloud-init, which runs once at first boot, so a `terraform apply` changes neither
on a live VM:

```bash
az vm run-command invoke -g trd365-maintenance -n trd365-maint-vm \
  --command-id RunShellScript \
  --scripts "/opt/trd365/app/infra/deploy/set-entra.sh <tenant-id> <client-id>"
```

That script moves the three things that have to move together — the service
learns the tenant and client, `TRD365_DEV_AUTH` goes off, and Caddy stops asking
for the shared password and stops injecting a role. It takes the redirect URI
from the hostname Caddy is actually serving, so the two cannot disagree. Then it
checks that the service reports `entra id` and **puts everything back if it does
not** — the likeliest cause being a vault missing one of the two secrets. Undo
with `set-entra.sh --off`.

**The next rebuild.** Record it in `infra/terraform/deployment.auto.tfvars`, which
is committed and auto-loaded and holds no secrets:

```hcl
entra_tenant_id = "b6734060-665c-4b7b-94e2-716458c1d933"
entra_client_id = "<the client id>"
public_hostname = "tech-controlcentre.certainti.ai"
```

`terraform apply` — which will report **no changes**, and that is correct.
`custom_data` is in the VM's `ignore_changes` because Azure treats it as
replace-only: without that, Terraform would offer to destroy and recreate the VM
to deliver a file, taking the audit trail and the model snapshots with it. The
tfvars entry is what makes a future rebuild come up already configured.

**Last, take away the shared password.** Set `demo_password = null` and
`demo_roles = "viewer"`, or turn `expose_publicly` off entirely if the host should
only be reachable from the office. A credential that still works is still a
credential.

---

## 5. Verifying it

```bash
HOST=tech-controlcentre.certainti.ai

# Says which authenticator is in force.
curl -s https://$HOST/api | jq .authentication      # -> "entra id"

# No session: nothing readable, even with a forged role header.
curl -s -o /dev/null -w '%{http_code}\n' https://$HOST/api/utilities            # 403
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Dev-Roles: admin' \
  https://$HOST/api/utilities                                                    # 403
```

Then sign in through a browser and check the sidebar shows your name and the roles
you were assigned. Every audit record from then on carries your address rather
than `demo`, which is the practical reason to do this at all.

---

## 6. If you would rather assign existing security groups

Some tenants prefer this to creating app roles. Both work, and both can be on at
once — the roles are unioned.

1. Token configuration → Add groups claim → **Security groups**, and tick
   **Emit groups as role claims** off (we want the `groups` claim).
2. Set `entra_group_roles` to the mapping, using group **object ids**:

```hcl
entra_group_roles = "aaaa-1111=operator,bbbb-2222=approver,cccc-3333=viewer"
```

App roles are still the better default: the assignment lives in Entra where it can
be audited and delegated, the claim stays small, and there are no group ids to
keep in step here. This exists because "we already have a group for the DBA team"
is a reasonable position and should not be a reason to stay on a shared password.

> Tenants with users in many groups should turn on group filtering, or Entra will
> emit a `groups` overage claim instead of the list and the mapping will find
> nothing. App roles do not have this problem.

---

## 7. What is deliberately not done

* **No Graph permissions for the application.** It reads identity from the token
  and nothing else. No directory read, no mail, no profile photo. A permission not
  requested is one nobody has to review. (The *deployment* permission in §4 Route
  A is a different thing: it creates the registration, and the application itself
  still asks for nothing.)
* **No refresh tokens.** A session lasts eight hours and then Entra is asked
  again. Long-lived offline access to an application that can delete production
  data is not worth the convenience.
* **No local accounts** (PRD FR-4.1). Once this is on, the only way in is the
  tenant, and access is a list somebody maintains.
