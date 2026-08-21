#!/usr/bin/env bash
# Install and configure Caddy in front of the application.
#
#   sudo /opt/trd365/app/infra/deploy/setup-caddy.sh <username> <password>
#
# Run by cloud-init when Terraform's `expose_publicly` is set. Safe to re-run:
# it reinstalls nothing that is already present and simply rewrites the
# credential file and reloads.
#
# Why Caddy rather than opening the application port directly: it terminates TLS
# with a real certificate, holds the login, and — the part that matters — decides
# what identity reaches the service. The Caddyfile injects the `viewer` role and
# nothing else, and the service refuses to start any utility that writes without
# operator or admin. Every registered utility writes. So whoever gets through the
# login can read and cannot run, by construction rather than by trust.
#
# This is still a demonstration posture. One shared secret, no record of who used
# it, and an authenticator the service ships for development. Entra ID SSO
# (PRD FR-3.x) is the real answer; turn this off when that lands.

set -Eeuo pipefail

USERNAME=${1:?usage: setup-caddy.sh <username> <password>}
PASSWORD=${2:?usage: setup-caddy.sh <username> <password>}

STAGED=/etc/trd365/Caddyfile
CADDYFILE=/etc/caddy/Caddyfile
CREDENTIALS=/etc/caddy/demo.env

log() { printf '[caddy] %s\n' "$*"; }
fail() { printf '[caddy] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "$STAGED" ]] || fail "$STAGED is missing; cloud-init should have written it"

install -d -m 0755 /etc/caddy /etc/systemd/system/caddy.service.d

# ------------------------------------------------------------------- install

if ! command -v caddy >/dev/null 2>&1; then
  log "installing caddy"
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg

  # Caddy's own signed apt repository. Keyring rather than apt-key, which is
  # deprecated and puts the key in a trust store used for every repository.
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  # --force-confold so a conffile that already exists can never turn this into
  # an interactive prompt on a host with no stdin.
  apt-get install -y -qq -o Dpkg::Options::=--force-confold caddy
else
  log "caddy already installed ($(caddy version | head -1))"
fi

# ------------------------------------------------------------------- config

# After the package, so dpkg owns the file before we overwrite it.
log "installing the configuration"
install -m 0644 "$STAGED" "$CADDYFILE"

# --------------------------------------------------------------- credentials

# The password is hashed here and the plain text never lands on disk. The file is
# root-owned and group-readable by caddy only.
log "writing the credential file"
HASH=$(caddy hash-password --plaintext "$PASSWORD")
printf 'TRD365_DEMO_USER=%s\nTRD365_DEMO_HASH=%s\n' "$USERNAME" "$HASH" > "$CREDENTIALS"
chown root:caddy "$CREDENTIALS"
chmod 0640 "$CREDENTIALS"

# --------------------------------------------------------------------- start

systemctl daemon-reload

# Validate before restarting, so a bad config leaves the previous one serving
# rather than taking the site down.
#
# The values are passed straight to the command rather than sourced from the file.
# A bcrypt hash is literally `$2a$14$…`, and sourcing that under `set -u` makes
# bash try to expand `$2a` and abort with "unbound variable" — which is exactly
# what stopped this script before it ever started the service. systemd's
# EnvironmentFile does no expansion, so the file itself is fine; only shell
# sourcing is the hazard.
log "validating the configuration"
TRD365_DEMO_USER="$USERNAME" TRD365_DEMO_HASH="$HASH" \
  caddy validate --config "$CADDYFILE" >/dev/null 2>&1 \
  || fail "$CADDYFILE is not valid; leaving the running config alone"

log "starting caddy"
systemctl enable --now caddy
systemctl restart caddy
sleep 3
systemctl is-active --quiet caddy || fail "caddy did not start; journalctl -u caddy -n 50"

log "caddy is serving. A certificate can take a minute to be issued on first boot."
