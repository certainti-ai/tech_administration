#!/usr/bin/env bash
# Install or update the application on the maintenance VM.
#
# Run as the trd365 service account:
#   sudo -u trd365 /opt/trd365/deploy.sh
# or remotely, without needing inbound SSH:
#   az vm run-command invoke -g <rg> -n <vm> --command-id RunShellScript \
#     --scripts 'sudo -u trd365 /opt/trd365/deploy.sh'
#
# Idempotent: safe to run repeatedly, and re-running is how you deploy a new
# commit.

set -Eeuo pipefail

ENV_FILE=/etc/trd365/environment
APP_DIR=/opt/trd365/app
VENV=/opt/trd365/venv

log() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "$ENV_FILE" ]] || fail "$ENV_FILE is missing. Was cloud-init completed?"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${TRD365_REPO_URL:?not set in $ENV_FILE}"
: "${TRD365_BRANCH:?not set in $ENV_FILE}"

# ---------------------------------------------------------------- fetch source

if [[ -d "$APP_DIR/.git" ]]; then
  log "updating $APP_DIR to origin/$TRD365_BRANCH"
  git -C "$APP_DIR" fetch --quiet origin "$TRD365_BRANCH"
  git -C "$APP_DIR" checkout --quiet "$TRD365_BRANCH"
  # Hard reset rather than merge: the VM is a deployment target, never a place
  # where edits are made, so local divergence is corruption and not work.
  git -C "$APP_DIR" reset --hard --quiet "origin/$TRD365_BRANCH"
else
  log "cloning $TRD365_REPO_URL"
  git clone --quiet --branch "$TRD365_BRANCH" "$TRD365_REPO_URL" "$APP_DIR"
fi

REVISION=$(git -C "$APP_DIR" rev-parse --short HEAD)
log "at revision $REVISION"

# -------------------------------------------------------------- install python

shopt -s nullglob
PACKAGES=("$APP_DIR"/packages/*/pyproject.toml)
[[ ${#PACKAGES[@]} -gt 0 ]] || fail "no packages found under $APP_DIR/packages"

for pyproject in "${PACKAGES[@]}"; do
  package_dir=$(dirname "$pyproject")
  log "installing $(basename "$package_dir")"
  "$VENV/bin/pip" install --quiet --upgrade "$package_dir"
done

# ------------------------------------------------------------- start if we can
#
# The service entry point arrives in Phase 2. Until then the VM is still useful
# — the utilities and the data-model analysis run from the CLI — so a missing
# orchestrator is reported, not treated as a failed deploy.

if "$VENV/bin/python" -c "import trd365_orchestrator" 2>/dev/null; then
  log "restarting trd365-admin"
  sudo systemctl restart trd365-admin.service
  sleep 3
  systemctl is-active --quiet trd365-admin.service \
    || fail "service failed to start; journalctl -u trd365-admin -n 50"
  log "service active on port ${TRD365_APP_PORT:-8080}"
else
  log "trd365_orchestrator not present (Phase 2 not built yet) — service left stopped."
  log "The CLI utilities are installed and usable:"
  log "  sudo -u trd365 $VENV/bin/python -m trd365_core --help"
fi

log "deploy complete at $REVISION"
