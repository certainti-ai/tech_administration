#!/usr/bin/env bash
# Change the name Caddy serves, on a VM that is already running.
#
#   sudo /opt/trd365/app/infra/deploy/set-hostname.sh tech-controlcentre.certainti.ai
#
# Why this exists. The site address comes from Terraform's `public_hostname`,
# which reaches the VM through cloud-init — and cloud-init's `write_files` runs
# once, at first boot. `terraform apply` with a new hostname therefore updates the
# plan and changes nothing on a live host: the file it would write is only written
# to a machine being created. Rebuilding the VM to rename it is not a trade worth
# making, so this edits the two files in place instead.
#
# It rewrites the site address only. Everything else in the Caddyfile — the auth
# stanza, the identity headers, the security headers — is left exactly as
# Terraform rendered it, so this cannot quietly undo a change made there.
#
# Run `terraform apply` with the same value afterwards (or before; the order does
# not matter) so a future rebuild comes up with the right name. Until you do, the
# two disagree and the next rebuild reverts the host.

set -Eeuo pipefail

HOSTNAME_NEW=${1:?usage: set-hostname.sh <hostname>}

STAGED=/etc/trd365/Caddyfile
CADDYFILE=/etc/caddy/Caddyfile
CREDENTIALS=/etc/caddy/demo.env

log() { printf '[hostname] %s\n' "$*"; }
fail() { printf '[hostname] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$HOSTNAME_NEW" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ ]] \
  || fail "'$HOSTNAME_NEW' is not a bare hostname (no scheme, no path, no trailing dot)"

# Resolve it before touching anything. Caddy asks Let's Encrypt for a certificate
# over HTTP-01 the moment it reloads, and a name that does not point here fails
# that challenge — repeatedly, and rate-limited. Better to stop now with a clear
# reason than to reload into a site that cannot get a certificate.
MINE=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)
RESOLVED=$(getent ahostsv4 "$HOSTNAME_NEW" | awk 'NR==1{print $1}' || true)
if [[ -z "$RESOLVED" ]]; then
  fail "$HOSTNAME_NEW does not resolve. Add the A record first; DNS can take a few minutes."
elif [[ -n "$MINE" && "$RESOLVED" != "$MINE" ]]; then
  fail "$HOSTNAME_NEW resolves to $RESOLVED, but this host is $MINE. Fix the A record first."
else
  log "$HOSTNAME_NEW resolves to $RESOLVED"
fi

[[ -r "$CADDYFILE" ]] || fail "$CADDYFILE is missing; is this host exposed at all?"

# The site address is the one line ending in ` {` that is not inside a block: the
# first such line after the global options. Matching on "the line before
# `encode`" is more fragile than matching the shape of the address itself.
rewrite() {
  local file=$1
  if [[ ! -r "$file" ]]; then
    log "$file absent, skipping"
    return 0
  fi
  local before
  before=$(awk '/^[^[:space:]{].*\{$/ {print $1; exit}' "$file")
  [[ -n "$before" ]] || fail "no site address found in $file"
  if [[ "$before" == "$HOSTNAME_NEW" ]]; then
    log "$file: already serving $HOSTNAME_NEW"
    return 0
  fi
  log "$file: $before -> $HOSTNAME_NEW"
  cp -a "$file" "$file.before-$HOSTNAME_NEW"
  awk -v new="$HOSTNAME_NEW" '
    !done && /^[^[:space:]{].*\{$/ { sub(/^[^[:space:]]+/, new); done = 1 }
    { print }
  ' "$file.before-$HOSTNAME_NEW" > "$file"
}

rewrite "$STAGED"
rewrite "$CADDYFILE"

# Validate with the credentials in scope, because the Caddyfile references them
# by environment placeholder when the shared login is still in use. Sourcing the
# file is not safe (a bcrypt hash starts `$2a$`, which bash would try to expand),
# so read it with a loop that does no expansion.
declare -a ENV_ARGS=()
if [[ -r "$CREDENTIALS" ]]; then
  while IFS='=' read -r key value; do
    [[ -n "$key" ]] && ENV_ARGS+=("$key=$value")
  done < "$CREDENTIALS"
fi

log "validating"
env "${ENV_ARGS[@]}" caddy validate --config "$CADDYFILE" >/dev/null 2>&1 \
  || fail "$CADDYFILE is not valid after the rewrite; the previous config is at $CADDYFILE.before-$HOSTNAME_NEW and is still what is running"

log "reloading"
systemctl reload caddy || systemctl restart caddy
sleep 3
systemctl is-active --quiet caddy || fail "caddy is not running; journalctl -u caddy -n 50"

log "serving $HOSTNAME_NEW. The first certificate takes up to a minute."
log "check: curl -sI https://$HOSTNAME_NEW/ | head -1"
