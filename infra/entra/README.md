# The Entra ID app registration, as code

Everything `docs/SSO.md` §3 describes as clicking, expressed as Terraform. Apply
it once and the app registration, its four roles, the "assignment required"
switch, the client secret and the session signing secret all exist — with the
secrets written straight into the Key Vault the VM already reads.

## Why this is a separate root module

It needs credentials the maintenance deployment deliberately does not have.

The deployer service principal (`7b8767e1-…`) holds **no** Microsoft Graph
application permissions at all — checked, not assumed: its access token carries no
`roles` claim, and Graph answers 403 to reading even the organisation's own name.
That is the correct posture for a service principal whose job is to build a VM. A
deployment identity that can also mint app registrations and assign roles in the
directory is a much larger thing to have leaked.

So this module is applied by somebody who already has directory rights, from their
own machine, once. Keeping it out of `infra/terraform` means the VM's state file
never has to be touched by an identity with directory write, and the VM's own
`terraform apply` cannot be the thing that changes who can sign in.

## Applying it

```bash
cd infra/entra
terraform init

# Sign in as yourself. Needs Application Administrator (or Cloud Application
# Administrator) to create the registration, and Key Vault Secrets Officer on the
# maintenance vault to store the two secrets.
az login --tenant b6734060-665c-4b7b-94e2-716458c1d933

terraform apply \
  -var public_hostname=tech-controlcentre.certainti.ai \
  -var key_vault_name=trd365-maint-kv-9qgdg5
```

`public_hostname` must match `public_hostname` in `infra/terraform` — the redirect
URI is derived from it, and the two disagreeing is `AADSTS50011` at sign-in with
nothing logged on this side to explain it.

If you hold Application Administrator but not Key Vault Secrets Officer, add
`-var write_secrets_to_vault=false`; the two secrets come out as sensitive
outputs for somebody who does to store with `az keyvault secret set`.

It prints the client id. Put that, and the hostname, into the VM's tfvars:

```hcl
entra_tenant_id = "b6734060-665c-4b7b-94e2-716458c1d933"
entra_client_id = "<the output>"
public_hostname = "tech-controlcentre.certainti.ai"
```

## What it does not do

**Assign anybody.** Who gets `viewer`, who gets `operator`, who gets `approver` is
a decision about your organisation, not something to infer. Pass group object ids
if you want them assigned here:

```bash
terraform apply \
  -var public_hostname=tech-controlcentre.certainti.ai \
  -var key_vault_name=trd365-maint-kv-9qgdg5 \
  -var 'operator_group_ids=["<dba-team-object-id>"]' \
  -var 'viewer_group_ids=["<support-team-object-id>"]'
```

Or leave them empty and assign in the portal — the module is happy either way, and
`assignment_required` means nobody gets in until somebody is.

## Running it from the deployment service principal instead

If this should be applied unattended rather than by a person, the service
principal needs exactly one Microsoft Graph **application** permission, with admin
consent: **`Application.ReadWrite.OwnedBy`**. That is enough to create and manage
the registration it owns, and nothing else in the directory.

Do not add `Application.ReadWrite.All` (the same power over every registration in
the tenant) or `AppRoleAssignment.ReadWrite.All` (which would also cover the group
assignments above — and lets its holder grant any app role of any application to
any principal, itself included). Group assignment is deliberately left to a person
in the portal for that reason.
