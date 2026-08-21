#!/usr/bin/env bash
# Turn Entra ID sign-in on (or off) on a VM that is already running.
#
#   sudo /opt/trd365/app/infra/deploy/set-entra.sh <tenant-id> <client-id> [hostname]
#   sudo /opt/trd365/app/infra/deploy/set-entra.sh --off
#
# The companion to set-hostname.sh, and it exists for the same reason: both
# /etc/trd365/environment and /etc/trd365/Caddyfile are written by cloud-init,
# which runs once at first boot. `terraform apply -var entra_tenant_id=...`
# therefore changes the plan and nothing on a live host.
#
# Three things have to move together, which is the whole argument for a script
# rather than three edits:
#
#   1. the service learns the tenant, client and redirect URI;
#   2. TRD365_DEV_AUTH goes off, so no header can name its own roles;
#   3. Caddy stops asking for the shared password and stops injecting an
#      identity — a password prompt in front of Microsoft's is two logins, and an
#      injected role in front of a verified token is an unverified claim.
#
# If the service does not come up, everything is put back and Caddy is left
# serving the configuration that was working. The two secrets are NOT set here:
# they live in the Key Vault as `entra-client-secret` and
# `session-signing-secret` and are read through the VM's managed identity.

set -Eeuo pipefail

ENV_FILE=/etc/trd365/environment
STAGED=/etc/trd365/Caddyfile
CADDYFILE=/etc/caddy/Caddyfile
CREDENTIALS=/etc/caddy/demo.env
SERVICE=trd365-admin.service
SUFFIX=.before-entra

log() { printf '[entra] %s\n' "$*"; }
fail() { printf '[entra] ERROR: %s\n' "$*" >&2; exit 1; }

GUID='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

if [[ ${1:-} == "--off" ]]; then
  MODE=off
  TENANT=""
  CLIENT=""
else
  MODE=on
  TENANT=${1:?usage: set-entra.sh <tenant-id> <client-id> [hostname] | --off}
  CLIENT=${2:?usage: set-entra.sh <tenant-id> <client-id> [hostname] | --off}
  [[ $TENANT =~ $GUID ]] || fail "'$TENANT' is not a tenant id (a GUID)"
  [[ $CLIENT =~ $GUID ]] || fail "'$CLIENT' is not a client id (a GUID)"
fi

[[ -r "$ENV_FILE" ]] || fail "$ENV_FILE is missing"
[[ -r "$CADDYFILE" ]] || fail "$CADDYFILE is missing; is this host exposed at all?"

# The hostname Caddy actually serves, unless overridden. Taking it from the file
# rather than an argument means the redirect URI cannot disagree with the site —
# which is the failure that produces AADSTS50011 and no log entry on this side.
site_address() { awk '/^[^[:space:]{].*\{$/ {print $1; exit}' "$CADDYFILE"; }
HOSTNAME_SERVED=${3:-$(site_address)}
[[ -n "$HOSTNAME_SERVED" ]] || fail "no site address found in $CADDYFILE"

if [[ $MODE == on ]]; then
  REDIRECT="https://$HOSTNAME_SERVED/auth/callback"
  log "tenant  $TENANT"
  log "client  $CLIENT"
  log "redirect $REDIRECT"
  case "$HOSTNAME_SERVED" in
    *.nip.io) log "NOTE: $HOSTNAME_SERVED is derived from the public IP. The redirect URI"
              log "      changes if that IP ever does. A real DNS name is better." ;;
  esac
else
  REDIRECT=""
  log "turning Entra off; the shared password comes back"
fi

# --------------------------------------------------------------- environment

cp -a "$ENV_FILE" "$ENV_FILE$SUFFIX"

# Rewrite in place: set the four keys if present, append them if not. sed on
# each key separately would leave a half-written file if one pattern missed.
python3 - "$ENV_FILE" "$TENANT" "$CLIENT" "$REDIRECT" "$MODE" <<'PY'
import sys

path, tenant, client, redirect, mode = sys.argv[1:6]
wanted = {
    "TRD365_DEV_AUTH": "0" if mode == "on" else "1",
    "TRD365_ENTRA_TENANT_ID": tenant,
    "TRD365_ENTRA_CLIENT_ID": client,
    "TRD365_ENTRA_REDIRECT_URI": redirect,
}
seen = set()
out = []
for line in open(path).read().splitlines():
    key = line.split("=", 1)[0].strip()
    if key in wanted and not line.lstrip().startswith("#"):
        out.append(f"{key}={wanted[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in wanted.items():
    if key not in seen:
        out.append(f"{key}={value}")
open(path, "w").write("\n".join(out) + "\n")
PY

log "$ENV_FILE updated"

# ------------------------------------------------------------------- caddy

# Drop the basic_auth block and the injected identity, or put them back. The
# block is removed by brace depth rather than by counting lines, so a Caddyfile
# whose formatting changes does not silently lose the wrong part of itself.
reshape_caddy() {
  local file=$1 mode=$2
  [[ -r "$file" ]] || { log "$file absent, skipping"; return 0; }
  cp -a "$file" "$file$SUFFIX"

  if [[ $mode == on ]]; then
    python3 - "$file$SUFFIX" "$file" <<'RESHAPE'
import re
import sys

source, target = sys.argv[1:3]
out, depth, skipping = [], 0, False
for line in open(source).read().splitlines():
    if skipping:
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            skipping = False
        continue
    if re.match(r"\s*basic_auth\s*\{", line):
        skipping, depth = True, 1
        continue
    if "header_up X-Dev-" in line:
        continue
    out.append(line)

# Removing the injected headers can leave `reverse_proxy host { }` with
# nothing in it. Caddy may well accept that; an empty block that exists only
# because something was deleted from it is still the wrong thing to leave.
collapsed = []
for line in out:
    if (
        collapsed
        and line.strip() == "}"
        and collapsed[-1].rstrip().endswith("{")
        and collapsed[-1].lstrip().startswith("reverse_proxy")
    ):
        collapsed[-1] = collapsed[-1].rstrip()[:-1].rstrip()
        continue
    collapsed.append(line)

# And the run of blank lines the basic_auth block left behind.
text = re.sub(r"\n{3,}", "\n\n", "\n".join(collapsed))
open(target, "w").write(text.rstrip("\n") + "\n")
RESHAPE
  else
    cp -a "$file$SUFFIX" "$file"
  fi
}

reshape_caddy "$STAGED" "$MODE"
reshape_caddy "$CADDYFILE" "$MODE"

# Validating needs the credential placeholders in scope while the shared login
# is still referenced. Read the file without sourcing it: a bcrypt hash begins
# `$2a$`, which bash would try to expand.
declare -a ENV_ARGS=()
if [[ -r "$CREDENTIALS" ]]; then
  while IFS='=' read -r key value; do
    [[ -n "$key" ]] && ENV_ARGS+=("$key=$value")
  done < "$CREDENTIALS"
fi

log "validating the Caddyfile"
env "${ENV_ARGS[@]}" caddy validate --config "$CADDYFILE" >/dev/null 2>&1 || {
  cp -a "$CADDYFILE$SUFFIX" "$CADDYFILE"
  cp -a "$ENV_FILE$SUFFIX" "$ENV_FILE"
  fail "the rewritten Caddyfile is not valid; nothing was changed"
}

# ------------------------------------------------------------- restart both

restore() {
  log "restoring the previous configuration"
  cp -a "$ENV_FILE$SUFFIX" "$ENV_FILE"
  cp -a "$CADDYFILE$SUFFIX" "$CADDYFILE"
  [[ -r "$STAGED$SUFFIX" ]] && cp -a "$STAGED$SUFFIX" "$STAGED"
  systemctl restart "$SERVICE" || true
  systemctl restart caddy || true
  fail "$1"
}

log "restarting $SERVICE"
systemctl restart "$SERVICE"
sleep 4
systemctl is-active --quiet "$SERVICE" || {
  journalctl -u "$SERVICE" -n 30 --no-pager | sed 's/^/    /'
  restore "the service did not come up — most likely the vault is missing entra-client-secret or session-signing-secret"
}

# The service reports which authenticator it settled on, so this is the one check
# that distinguishes "restarted" from "actually using Entra".
PORT=$(awk -F= '/^TRD365_APP_PORT=/{print $2}' "$ENV_FILE")
REPORTED=$(curl -fsS --max-time 10 "http://127.0.0.1:${PORT:-8080}/api" | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("authentication",""))' 2>/dev/null || true)
log "the service reports authentication: ${REPORTED:-(unreadable)}"
if [[ $MODE == on && $REPORTED != "entra id" ]]; then
  restore "the service is up but is not using Entra (reported '${REPORTED:-nothing}')"
fi

# Restart rather than reload: the Caddyfile sets `admin off`, so `caddy reload`
# has no admin endpoint to talk to and systemd's ExecReload always fails. A
# restart is the only thing that applies a new config here.
log "restarting caddy"
systemctl restart caddy
sleep 3
systemctl is-active --quiet caddy || restore "caddy did not come back"

log "done. https://$HOSTNAME_SERVED/ now signs in through Microsoft."
log "The shared password is still in $CREDENTIALS and is no longer asked for."
log "Remove it for real with: terraform apply -var demo_password=null"
