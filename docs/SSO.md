# Entra ID sign-in

How to put this application behind Microsoft sign-in for the certainti.ai tenant,
and how access is controlled once it is.

The code is written, tested and inert: with none of the `entra_*` Terraform
variables set, the deployment behaves exactly as it does today. Turning it on is
the checklist in §3, and everything in it happens in Entra ID — nothing here can
create an app registration, because the deployer service principal has no
directory permissions (verified: Microsoft Graph returns 403 for it, which is the
right answer).

Tenant: `b6734060-665c-4b7b-94e2-716458c1d933`.

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
  reaches us (§3, step 6), and the application refuses it again if it arrives
  anyway. Belt and braces, because the two are maintained by different people.

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

## 3. The checklist

All of this is in the Entra admin centre, in the certainti.ai tenant.

**1. Register the application.**
Entra ID → App registrations → New registration.

* Name: `Certainti Tech Administration`
* Supported account types: **Accounts in this organizational directory only**
  (single tenant). Anything wider is a larger blast radius for no benefit; the
  application checks the `tid` claim and would refuse other tenants anyway.
* Redirect URI: **Web** → `https://<your-host>/auth/callback`

Note the **Application (client) ID**.

> The host must match what Caddy serves. Terraform derives the redirect URI from
> it for exactly this reason — the two disagreeing produces a redirect-URI
> mismatch with no obvious cause. Set `public_hostname` to a real name before
> turning SSO on; the `nip.io` fallback works, but the URI changes if the VM's
> public IP ever does.

**2. Create a client secret.**
Certificates & secrets → New client secret. Copy it now; it is not shown again.
A certificate is better if you would rather not rotate a secret — say so and I
will switch the code to one.

**3. Define the four app roles.**
App roles → Create app role, four times. The **value** is what the application
reads and must be exactly:

| Display name | Value | Allowed member types |
|---|---|---|
| Viewer | `viewer` | Users/Groups |
| Operator | `operator` | Users/Groups |
| Approver | `approver` | Users/Groups |
| Administrator | `admin` | Users/Groups |

**4. Emit the roles.** Token configuration → the `roles` claim is included for
app roles automatically. Nothing to do unless you chose groups instead — see §5.

**5. Assign people.**
Enterprise applications → Certainti Tech Administration → Users and groups → Add
user/group, choosing a role each time. Groups are better than people.

**6. Require assignment.**
Enterprise applications → the same app → Properties → **Assignment required:
Yes**.

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

**8. Turn it on.**

```hcl
entra_tenant_id = "b6734060-665c-4b7b-94e2-716458c1d933"
entra_client_id = "<from step 1>"
public_hostname = "techadmin.certainti.ai"   # or whatever DNS name you use
```

`terraform apply`. Caddy's password prompt disappears and `/` redirects to
Microsoft.

**9. Take away the shared password.** Set `demo_password = null` and
`demo_roles = "viewer"`, or turn `expose_publicly` off entirely if the host should
only be reachable from the office. A credential that still works is still a
credential.

---

## 4. Verifying it

```bash
# Says which authenticator is in force.
curl -s https://<host>/api | jq .authentication      # -> "entra id"

# No session: nothing readable, even with a forged role header.
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/utilities            # 403
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Dev-Roles: admin' \
  https://<host>/api/utilities                                                    # 403
```

Then sign in through a browser and check the sidebar shows your name and the roles
you were assigned. Every audit record from then on carries your address rather
than `demo`, which is the practical reason to do this at all.

---

## 5. If you would rather assign existing security groups

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

## 6. What is deliberately not done

* **No Graph permissions.** The application reads identity from the token and
  nothing else. No directory read, no mail, no profile photo. A permission not
  requested is one nobody has to review.
* **No refresh tokens.** A session lasts eight hours and then Entra is asked
  again. Long-lived offline access to an application that can delete production
  data is not worth the convenience.
* **No local accounts** (PRD FR-4.1). Once this is on, the only way in is the
  tenant, and access is a list somebody maintains.
