#!/usr/bin/env bash
# Install or update the application on the maintenance VM.
#
#   sudo -u trd365 /opt/trd365/deploy.sh              # fetch, install, test, restart
#   sudo -u trd365 /opt/trd365/deploy.sh --skip-tests # force, when you know why
#
# or remotely, without needing inbound SSH:
#   az vm run-command invoke -g <rg> -n <vm> --command-id RunShellScript \
#     --scripts 'sudo -u trd365 /opt/trd365/deploy.sh'
#
# Idempotent: safe to run repeatedly, and re-running is how you deploy a new
# commit. trd365-deploy.timer runs it on a schedule, so a push to the deployed
# branch reaches the VM on its own.
#
# The test gate is the point. This host holds credentials that can delete
# production data, and an unattended deploy means code arrives here without
# anyone watching. So a new revision has to pass the suite before the service is
# restarted onto it; if it does not, the checkout is rolled back to the revision
# that was serving and the running service is never touched. A VM left on last
# week's good commit is a nuisance. A VM running a broken build against
# production is not.

set -Eeuo pipefail

ENV_FILE=/etc/trd365/environment
APP_DIR=/opt/trd365/app
VENV=/opt/trd365/venv
SERVICE=trd365-admin.service

SKIP_TESTS=0
[[ "${1:-}" == "--skip-tests" ]] && SKIP_TESTS=1

log() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "$ENV_FILE" ]] || fail "$ENV_FILE is missing. Was cloud-init completed?"
set -a
# shellcheck source=/dev/null  # written by cloud-init; absent at lint time
source "$ENV_FILE"
set +a

: "${TRD365_REPO_URL:?not set in $ENV_FILE}"
: "${TRD365_BRANCH:?not set in $ENV_FILE}"

install_packages() {
  shopt -s nullglob
  local pyprojects=("$APP_DIR"/packages/*/pyproject.toml)
  [[ ${#pyprojects[@]} -gt 0 ]] || fail "no packages found under $APP_DIR/packages"
  for pyproject in "${pyprojects[@]}"; do
    local dir
    dir=$(dirname "$pyproject")
    # Braced: "$dir[dev]" reads as an array subscript, not a pip extra.
    "$VENV/bin/pip" install --quiet --upgrade "${dir}[dev]" \
      || "$VENV/bin/pip" install --quiet --upgrade "$dir"
  done
}

run_tests() {
  # Per package, never `pytest packages/`: each carries its own config
  # (asyncio_mode, testpaths) and a repo-root rootdir silently ignores all of it.
  shopt -s nullglob
  local failed=()
  for pyproject in "$APP_DIR"/packages/*/pyproject.toml; do
    local dir name
    dir=$(dirname "$pyproject")
    name=$(basename "$dir")
    local logfile="/tmp/trd365-test-$name.log"
    if ! (cd "$dir" && "$VENV/bin/python" -m pytest -q >"$logfile" 2>&1); then
      failed+=("$name")
      log "  FAILED $name — see $logfile"
      tail -n 15 "$logfile" | sed 's/^/    /'
    fi
  done
  [[ ${#failed[@]} -eq 0 ]] || return 1
}

# ---------------------------------------------------------------- fetch source

if [[ -d "$APP_DIR/.git" ]]; then
  PREVIOUS=$(git -C "$APP_DIR" rev-parse HEAD)
  log "updating $APP_DIR to origin/$TRD365_BRANCH (currently ${PREVIOUS:0:8})"
  git -C "$APP_DIR" fetch --quiet origin "$TRD365_BRANCH"
  git -C "$APP_DIR" checkout --quiet "$TRD365_BRANCH"
  # Hard reset rather than merge: the VM is a deployment target, never a place
  # where edits are made, so local divergence is corruption and not work.
  git -C "$APP_DIR" reset --hard --quiet "origin/$TRD365_BRANCH"
else
  PREVIOUS=""
  log "cloning $TRD365_REPO_URL"
  git clone --quiet --branch "$TRD365_BRANCH" "$TRD365_REPO_URL" "$APP_DIR"
fi

REVISION=$(git -C "$APP_DIR" rev-parse HEAD)

installed() { "$VENV/bin/python" -c "import trd365_core" 2>/dev/null; }

# "Same revision" is only the same if the packages from it are actually
# installed. On a fresh VM cloud-init makes the first clone, so the first deploy
# finds the revision unchanged while nothing is installed at all — and the fast
# path below would skip the install, skip the tests, and try to start a service
# with no code behind it. Check both.
if [[ -n "$PREVIOUS" && "$PREVIOUS" == "$REVISION" ]] && installed; then
  log "already at ${REVISION:0:8} and installed; nothing to deploy"
  # Still make sure the service is up — a timer run is also a health check.
  systemctl is-active --quiet "$SERVICE" || {
    log "service is not running; starting it"
    sudo systemctl start "$SERVICE"
  }
  exit 0
fi

if [[ -n "$PREVIOUS" && "$PREVIOUS" == "$REVISION" ]]; then
  log "at ${REVISION:0:8} but the packages are not installed; installing"
fi

log "deploying ${REVISION:0:8}"

# -------------------------------------------------------------- install python

install_packages

# ---------------------------------------------------------------- gate on tests

roll_back() {
  local reason="$1"
  if [[ -z "$PREVIOUS" ]]; then
    fail "$reason, and there is no previous revision to fall back to. \
The service was not started. Fix the commit and re-run."
  fi
  log "rolling back to ${PREVIOUS:0:8} because $reason"
  git -C "$APP_DIR" reset --hard --quiet "$PREVIOUS"
  install_packages
  log "rolled back. The service is still on ${PREVIOUS:0:8}."
  fail "$reason — ${REVISION:0:8} was NOT deployed"
}

if [[ "$SKIP_TESTS" -eq 1 ]]; then
  log "skipping tests by request"
elif ! "$VENV/bin/python" -c "import pytest" 2>/dev/null; then
  # Better to say so than to silently deploy an ungated revision.
  log "WARNING: pytest is not installed in the venv, so this revision is ungated"
else
  log "running the test suite before restarting"
  run_tests || roll_back "the test suite failed"
  log "tests passed"
fi

# ------------------------------------------------------------------ restart

if ! "$VENV/bin/python" -c "import trd365_orchestrator" 2>/dev/null; then
  # The utilities are still usable from the CLI without the service.
  log "trd365_orchestrator is not installed — service left alone."
  log "CLI utilities are available: sudo -u trd365 $VENV/bin/python -m trd365_data_purge.account --help"
  log "deploy complete at ${REVISION:0:8}"
  exit 0
fi

log "restarting $SERVICE"
sudo systemctl restart "$SERVICE"
sleep 3

if ! systemctl is-active --quiet "$SERVICE"; then
  journalctl -u "$SERVICE" -n 30 --no-pager | sed 's/^/    /'
  roll_back "the service did not come up"
fi

log "service active on port ${TRD365_APP_PORT:-8080}"
log "deploy complete at ${REVISION:0:8}"
