# The live deployment's non-secret settings, auto-loaded by Terraform.
#
# This exists so a rebuild comes up as itself. Everything here was previously a
# `-var` on somebody's command line, which is fine until the person who knows
# the flags is not the one running the apply.
#
# Secrets are NOT here and must not be added: `demo_password` is passed on the
# command line, and every database credential comes from the Key Vault. Anything
# in this file is in git.

# Reachable from the internet, behind Caddy. Turning this off removes the public
# IP and the inbound rules; see docs/HANDOFF.md 13.
expose_publicly = true

# A real name, so the redirect URI Entra has registered stays true. The A record
# lives in GoDaddy and points at this VM's static public IP.
public_hostname = "tech-controlcentre.certainti.ai"

# Entra ID sign-in. Filled in from `terraform output client_id` in infra/entra;
# empty means the shared login is still in force, which the service reports at
# /api as "development headers" rather than "entra id".
entra_tenant_id = "b6734060-665c-4b7b-94e2-716458c1d933"
entra_client_id = "d1db5f12-d7fb-4f14-8a01-71dc5bd5cf4a"
