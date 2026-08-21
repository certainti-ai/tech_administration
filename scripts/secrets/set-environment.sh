#!/usr/bin/env bash
# Put one deployment environment's database credentials into the Key Vault.
#
#   ./set-environment.sh <dev|qa|stage|prod> <file>            # dry run
#   ./set-environment.sh <dev|qa|stage|prod> <file> --apply
#   ./set-environment.sh <dev|qa|stage|prod> --from-env [--apply]
#
# Only the values that must not be in a repository are written: the passwords.
# Hosts, ports, users, sslmode and the bastion address are in
# `trd365_core.environments`, and the resolver checks the vault *before* falling
# back to that, so a copy in the vault silently wins over the code. Two sources
# of truth where the quieter one wins is how a corrected hostname gets ignored
# for a week. Pass `--with-overrides` to write them anyway, deliberately, when
# something needs changing without a release.
#
# `--from-env` reads the values from this process's environment instead of a
# file, for a context that already has them — a session whose environment
# carries them, or CI. It reads **only** the fully scoped names
# (`TRD365_QA_MAINDB_PASSWORD`), never the unscoped ones: a bare
# `MAINDB_PASSWORD` in a shell is exactly the ambiguity the prefix exists to
# remove, and storing it under a scoped vault name would attribute one
# environment's password to another with nothing to show it had happened.
#
# Dry run by default. It prints every secret name it would write and a short
# digest of each value — enough to confirm a value is the one you meant without
# it appearing on screen, in a shell history, or in a CI log.
#
# **It asks the code what it needs.** Servers, ports, users and bastions live in
# `trd365_core.environments`, where they are reviewable and version-controlled;
# only the things that must not be in git are asked for here. So the required
# list is derived from that module rather than restated: Dev and QA want four
# values, Stage wants six because it goes through a bastion, and a database whose
# server this repo does not know is skipped rather than half-configured.
#
# The names are derived too, for the same reason. `trd365_core` looks up
# `TRD365_<ENV>_<DBKEY>_<FIELD>`, lowercased with underscores turned to hyphens,
# and a name that is close but wrong does not error — the field falls back to a
# placeholder, the utility then refuses to run, and the message names a
# credential you are certain you supplied.
#
# Values are passed to `az` through a mode-0600 file, never as an argument:
# arguments are visible in /proc to anybody on the machine.

set -Eeuo pipefail

USAGE="usage: set-environment.sh <dev|qa|stage|prod> <file|--from-env> [--apply]"

ENVIRONMENT=${1:?$USAGE}
SOURCE=${2:?$USAGE}
APPLY=${3:-}

FROM_ENV=false
if [[ "$SOURCE" == "--from-env" ]]; then
  FROM_ENV=true
  SOURCE="the environment"
fi

# --with-overrides may appear in either trailing position.
WITH_OVERRIDES=false
for argument in "${@:3}"; do
  [[ "$argument" == "--with-overrides" ]] && WITH_OVERRIDES=true
done
[[ "$APPLY" == "--with-overrides" ]] && APPLY=${4:-}

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CORE_SRC="$HERE/../../packages/trd365-core/src"
VAULT=${AZURE_KEY_VAULT_NAME:-trd365-maint-kv-9qgdg5}

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "$ENVIRONMENT" in
  dev|qa|stage|prod) ;;
  *) fail "'$ENVIRONMENT' is not one of dev, qa, stage, prod" ;;
esac
[[ "$FROM_ENV" == true || -r "$SOURCE" ]] || fail "cannot read $SOURCE"
[[ -z "$APPLY" || "$APPLY" == "--apply" ]] || fail "unexpected argument '$APPLY'"
[[ -d "$CORE_SRC" ]] || fail "cannot find trd365-core at $CORE_SRC; run this from a checkout"

WORK=$(mktemp -d)
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT INT TERM

# ---------------------------------------------------------------- what to ask

# One line per field: "<db_key>\t<FIELD>\trequired|optional".
PYTHONPATH="$CORE_SRC" python3 - "$ENVIRONMENT" "$WITH_OVERRIDES" > "$WORK/wanted" <<'PY' || fail "could not read the topology from trd365_core"
import sys

from trd365_core.environments import DB_KEYS, PLACEHOLDER, Environment, describe

env = Environment(sys.argv[1])
with_overrides = sys.argv[2] == "true"

# Fields the code already knows. Written only when asked for: overriding a host
# or a user without a release is occasionally the difference between a diagnosis
# and a guess, but doing it by accident buries the real value.
OPTIONAL = ("HOST", "PORT", "DBNAME", "USER", "SSLMODE")
OPTIONAL_TUNNEL = ("SSH_HOST", "SSH_PORT", "SSH_USER")

for db_key in DB_KEYS:
    settings = describe(env, db_key, {})

    # No known server means no amount of secrets makes this database usable, and
    # asking for a password for a host nobody has named invites inventing one.
    if PLACEHOLDER in settings.host:
        continue

    required = ["PASSWORD"]
    if settings.dbname == PLACEHOLDER:
        required.insert(0, "DBNAME")
    if settings.ssh_tunnel is not None:
        required.append("SSH_PASSWORD")

    optional = list(OPTIONAL) if with_overrides else []
    if with_overrides and settings.ssh_tunnel is not None:
        optional += list(OPTIONAL_TUNNEL)

    for field in required:
        print(f"{db_key}\t{field}\trequired")
    for field in optional:
        print(f"{db_key}\t{field}\toptional")
PY

[[ -s "$WORK/wanted" ]] || fail "$ENVIRONMENT has no databases this repo knows a server for"

# --------------------------------------------------------------- what we have

if [[ "$FROM_ENV" == true ]]; then
  # Only the fields this environment actually wants, looked up by their scoped
  # name. Nothing else in the environment is read, so an unrelated variable that
  # happens to match a field name cannot become a credential.
  # The wanted list is passed as an argument, not on stdin: stdin is the
  # heredoc that carries this script.
  python3 - "$ENVIRONMENT" "$WORK/wanted" > "$WORK/parsed" <<'PY'
import os
import sys

environment, wanted = sys.argv[1:3]
prefix = f"TRD365_{environment.upper()}_"

for line in open(wanted, encoding="utf-8"):
    db_key, field, _requirement = line.rstrip("\n").split("\t")
    value = os.environ.get(f"{prefix}{db_key.upper()}_{field}")
    if value:
        print(f"{db_key.upper()}_{field}\t{value}")
PY
else
  # Read the file without sourcing it. A password containing `$`, backticks or a
  # space would otherwise be expanded, mangled, or executed.
  python3 - "$SOURCE" > "$WORK/parsed" <<'PY'
import sys

for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    print(f"{key.strip()}\t{value}")
PY
fi

lookup() {
  awk -F'\t' -v want="$1" '$1 == want { sub(/^[^\t]*\t/, ""); print; found = 1 } END { exit !found }' \
    "$WORK/parsed"
}

digest() { printf '%s' "$1" | sha256sum | cut -c1-12; }

missing=0
declare -a NAMES=() KEYS=()

log ""

while IFS=$'\t' read -r db_key field requirement; do
  key="$(printf '%s_%s' "$db_key" "$field" | tr '[:lower:]' '[:upper:]')"
  value=$(lookup "$key" || true)

  if [[ -z "$value" ]]; then
    if [[ "$requirement" == "required" ]]; then
      printf '  MISSING  %s\n' "$key"
      missing=$((missing + 1))
    fi
    continue
  fi

  NAMES+=("$(printf 'trd365-%s-%s-%s' "$ENVIRONMENT" "$db_key" "$field" | tr '[:upper:]_' '[:lower:]-')")
  KEYS+=("$key")
  printf '%s' "$value" > "$WORK/value.$key"
  chmod 600 "$WORK/value.$key"
done < "$WORK/wanted"

if [[ $missing -gt 0 ]]; then
  fail "$missing required field(s) are empty. See environment.env.example."
fi

# Anything in the file this environment has no use for. Not an error — filling in
# one file per environment from the same template is a reasonable way to work —
# but worth saying, because a password typed into a field nothing reads is a
# password somebody believes is in place.
if [[ "$FROM_ENV" == true && "$WITH_OVERRIDES" == false ]]; then
  log "  in code   host, port, dbname, user, sslmode and the bastion address"
  log "            (pass --with-overrides to store them in the vault as well)"
fi

while IFS=$'\t' read -r key _; do
  [[ "$FROM_ENV" == true ]] && break
  if ! awk -F'\t' -v k="$key" '
      { want = toupper($1 "_" $2); if (want == k) found = 1 }
      END { exit !found }' "$WORK/wanted"; then
    if [[ "$WITH_OVERRIDES" == false ]] && printf '%s' "$key" | grep -qE '_(HOST|PORT|DBNAME|USER|SSLMODE)$'; then
      printf '  in code   %s (pass --with-overrides to store it anyway)\n' "$key"
    else
      printf '  ignored   %s (not used by %s)\n' "$key" "$ENVIRONMENT"
    fi
  fi
done < "$WORK/parsed"

log ""
log "vault:       $VAULT"
log "environment: $ENVIRONMENT"
log ""
printf '  %-40s %-24s %s\n' "SECRET NAME" "FROM" "DIGEST"
for i in "${!NAMES[@]}"; do
  printf '  %-40s %-24s %s\n' "${NAMES[$i]}" "${KEYS[$i]}" \
    "$(digest "$(cat "$WORK/value.${KEYS[$i]}")")"
done
log ""

if [[ "$APPLY" != "--apply" ]]; then
  log "Dry run. Nothing was written. Re-run with --apply."
  exit 0
fi

command -v az >/dev/null || fail "the az CLI is needed for --apply"

for i in "${!NAMES[@]}"; do
  printf '  writing %s ... ' "${NAMES[$i]}"
  az keyvault secret set \
    --vault-name "$VAULT" \
    --name "${NAMES[$i]}" \
    --file "$WORK/value.${KEYS[$i]}" \
    --encoding utf-8 \
    --only-show-errors --output none
  printf 'done\n'
done

log ""
if [[ "$FROM_ENV" == true ]]; then
  log "Wrote ${#NAMES[@]} secrets, read from this process's environment."
else
  log "Wrote ${#NAMES[@]} secrets. Now delete $SOURCE — it still holds the passwords."
fi
log ""
log "Then check it from the VM, which reads the vault with its managed identity."
log "This is the only check that means anything: a secret written under a name"
log "nothing reads looks exactly like a secret that works."
log ""
log "  az vm run-command invoke -g trd365-maintenance -n trd365-maint-vm \\"
log "    --command-id RunShellScript --scripts \\"
log "    \"/opt/trd365/app/infra/deploy/verify.sh $ENVIRONMENT\""
