#!/usr/bin/env bash
# Put one deployment environment's database credentials into the Key Vault.
#
#   ./set-environment.sh <dev|qa|stage|prod> <file>            # dry run
#   ./set-environment.sh <dev|qa|stage|prod> <file> --apply
#
# Dry run by default. It prints every secret name it would write and a short
# digest of each value — enough to confirm a value is the one you meant without
# it appearing on screen, in a shell history, or in a CI log.
#
# Why a script rather than 26 `az keyvault secret set` commands: the name is the
# contract. `trd365_core.environments` looks for
# `TRD365_<ENV>_<DBKEY>_<FIELD>`, lowercased with underscores turned into
# hyphens, and a name that is close but wrong does not error — the field falls
# back to a placeholder, and the utility refuses to run with a message about a
# credential you are certain you supplied. Deriving the names here means they
# cannot be typed wrong.
#
# Values are passed to `az` through a mode-0600 file, never as an argument:
# arguments are visible in /proc to anybody on the machine.

set -Eeuo pipefail

ENVIRONMENT=${1:?usage: set-environment.sh <dev|qa|stage|prod> <file> [--apply]}
SOURCE=${2:?usage: set-environment.sh <dev|qa|stage|prod> <file> [--apply]}
APPLY=${3:-}

VAULT=${AZURE_KEY_VAULT_NAME:-trd365-maint-kv-9qgdg5}
PLACEHOLDER=PLACEHOLDER_NOT_CONFIGURED

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "$ENVIRONMENT" in
  dev|qa|stage|prod) ;;
  *) fail "'$ENVIRONMENT' is not one of dev, qa, stage, prod" ;;
esac
[[ -r "$SOURCE" ]] || fail "cannot read $SOURCE"
[[ -z "$APPLY" || "$APPLY" == "--apply" ]] || fail "unexpected argument '$APPLY'"

# The fields each database needs, and the order they are shown in. Kept in step
# with DB_KEYS and the ConnectionSettings dataclass in trd365_core.environments:
# a field here that the resolver does not read is dead weight, and one it reads
# that is missing here is a placeholder at run time.
MAINDB_FIELDS="HOST PORT DBNAME USER PASSWORD SSLMODE SSH_HOST SSH_PORT SSH_USER SSH_PASSWORD"
ORGDB_FIELDS="$MAINDB_FIELDS"
TRD365AI_FIELDS="HOST PORT DBNAME USER PASSWORD SSLMODE"

WORK=$(mktemp -d)
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT INT TERM

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

lookup() {
  awk -F'\t' -v want="$1" '$1 == want { sub(/^[^\t]*\t/, ""); print; found = 1 } END { exit !found }' \
    "$WORK/parsed"
}

secret_name() {
  # TRD365_QA_MAINDB_SSH_PASSWORD -> trd365-qa-maindb-ssh-password
  printf 'trd365-%s-%s-%s\n' "$ENVIRONMENT" "$1" "$2" | tr '[:upper:]_' '[:lower:]-'
}

digest() { printf '%s' "$1" | sha256sum | cut -c1-12; }

missing=0
declare -a NAMES=() KEYS=()

for db in maindb orgdb trd365ai; do
  case "$db" in
    maindb)   fields=$MAINDB_FIELDS ;;
    orgdb)    fields=$ORGDB_FIELDS ;;
    trd365ai) fields=$TRD365AI_FIELDS ;;
    *)        fail "unreachable" ;;
  esac

  for field in $fields; do
    key="$(printf '%s_%s' "$db" "$field" | tr '[:lower:]' '[:upper:]')"
    value=$(lookup "$key" || true)
    if [[ -z "$value" || "$value" == "$PLACEHOLDER" ]]; then
      printf '  MISSING  %s\n' "$key"
      missing=$((missing + 1))
      continue
    fi
    NAMES+=("$(secret_name "$db" "$field")")
    KEYS+=("$key")
    printf '%s' "$value" > "$WORK/value.$key"
    chmod 600 "$WORK/value.$key"
  done
done

if [[ $missing -gt 0 ]]; then
  fail "$missing field(s) are empty. Every field is required — see environment.env.example."
fi

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

if [[ "$ENVIRONMENT" == "prod" ]]; then
  log "NOTE: prod is already in the vault under unscoped names (maindb-host and"
  log "      friends), which the resolver still accepts for prod only. Writing the"
  log "      scoped copies here is safe and makes prod look like the others, but"
  log "      it is not required for anything to work."
  log ""
fi

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
log "Wrote ${#NAMES[@]} secrets. Now delete $SOURCE — it still holds the passwords."
log ""
log "Then check it from the VM, which reads the vault with its managed identity."
log "This is the only check that means anything: a secret written under a name"
log "nothing reads looks exactly like a secret that works."
log ""
log "  az vm run-command invoke -g trd365-maintenance -n trd365-maint-vm \\"
log "    --command-id RunShellScript --scripts \\"
log "    \"/opt/trd365/app/infra/deploy/verify.sh $ENVIRONMENT\""
log ""
log "Or open the console: the $ENVIRONMENT card moves from \"Credentials pending\""
log "to \"Connected\", naming any database that is still unreachable."
