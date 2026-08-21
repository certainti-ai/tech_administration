#!/usr/bin/env bash
# Run a utility on the VM detached, with its output in the journal.
#
#   run-utility.sh start  <name> <module> [args…]
#   run-utility.sh status <name>
#   run-utility.sh log    <name> [lines]
#   run-utility.sh stop   <name>
#
#   run-utility.sh start snapshot-dev trd365_analysis --env dev --apply
#   run-utility.sh log    snapshot-dev 40
#
# Why this exists. `az vm run-command` holds stdout until the command exits, so a
# job that takes twenty minutes is completely opaque for twenty minutes — and it
# occupies the single run-command slot, so nothing else can even ask how it is
# doing. Both were true of the first data-model snapshot: it logged progress per
# schema and none of it was visible.
#
# systemd-run fixes both. The job gets its own transient unit, journald captures
# the progress it was already writing, and the run-command that started it
# returns immediately.
#
# It refuses to start a second run of the same name, because two snapshots of one
# environment writing the same model file is a corrupted snapshot rather than two.

set -Eeuo pipefail

ACTION=${1:?usage: run-utility.sh start|status|log|stop <name> [module] [args…]}
NAME=${2:?usage: run-utility.sh start|status|log|stop <name> [module] [args…]}
UNIT="trd365-run-${NAME}"

ENV_FILE=/etc/trd365/environment
VENV=/opt/trd365/venv
USER_NAME=trd365

log() { printf '[run] %s\n' "$*"; }
fail() { printf '[run] ERROR: %s\n' "$*" >&2; exit 1; }

case "$ACTION" in
  start)
    MODULE=${3:?a module is required, e.g. trd365_analysis}
    shift 3
    [[ -r "$ENV_FILE" ]] || fail "$ENV_FILE is missing"
    [[ -x "$VENV/bin/python" ]] || fail "$VENV/bin/python is missing"

    if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
      fail "$UNIT is already running; use 'log $NAME' to watch it, or 'stop $NAME'"
    fi
    # A finished transient unit lingers in a failed/inactive state and would block
    # the next start; clearing it is not the same as stopping a live one.
    systemctl reset-failed "$UNIT" 2>/dev/null || true

    log "starting $UNIT: python -m $MODULE $*"
    systemd-run \
      --unit="$UNIT" \
      --description="trd365 $MODULE ($NAME)" \
      --uid="$USER_NAME" \
      --property=EnvironmentFile="$ENV_FILE" \
      --property=WorkingDirectory=/opt/trd365/app \
      --property=StandardOutput=journal \
      --property=StandardError=journal \
      --collect \
      "$VENV/bin/python" -u -m "$MODULE" "$@" >/dev/null
    log "started. Follow it with: $0 log $NAME"
    ;;

  status)
    if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
      log "$NAME is RUNNING"
      systemctl show "$UNIT" -p ExecMainStartTimestamp --value | sed 's/^/  started /'
    else
      code=$(systemctl show "$UNIT" -p ExecMainStatus --value 2>/dev/null || echo "")
      if [[ -n "$code" ]]; then
        log "$NAME has FINISHED, exit status ${code}"
      else
        log "$NAME has finished and its unit has already been collected"
      fi
    fi
    # The last line of output is usually the summary, so it is worth having here.
    journalctl -u "$UNIT" -n 3 --no-pager -o cat 2>/dev/null | sed 's/^/  /' || true
    ;;

  log)
    journalctl -u "$UNIT" -n "${3:-60}" --no-pager -o cat
    ;;

  stop)
    systemctl stop "$UNIT" && log "stopped $NAME"
    ;;

  *)
    fail "unknown action '$ACTION' (start, status, log, stop)"
    ;;
esac
