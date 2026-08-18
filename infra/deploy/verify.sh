#!/usr/bin/env bash
# Post-deploy checks. Run on the VM; safe, read-only, no writes anywhere.
#
# This is the script that answers the question the sandbox never could: can this
# host actually see the databases?

set -uo pipefail

ENV_FILE=/etc/trd365/environment
VENV=/opt/trd365/venv
failures=0

check() {
  local label=$1; shift
  if "$@" >/dev/null 2>&1; then
    printf '  ok    %s\n' "$label"
  else
    printf '  FAIL  %s\n' "$label"
    failures=$((failures + 1))
  fi
}

echo "== environment =="
[[ -r "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }
printf '  vault: %s\n' "${AZURE_KEY_VAULT_NAME:-(unset)}"
printf '  model dir: %s\n' "${TRD365_MODEL_DIR:-(unset)}"

echo "== managed identity can read the vault =="
check "IMDS token" curl -s --max-time 10 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://vault.azure.net"

echo "== python packages =="
check "trd365_core imports" "$VENV/bin/python" -c "import trd365_core"

echo "== database reachability (prod) =="
"$VENV/bin/python" - <<'PY'
import sys
from trd365_core import ConnectionPool, Environment, DB_KEYS
try:
    with ConnectionPool(Environment.PROD) as pool:
        for key in DB_KEYS:
            try:
                info = pool.verify(key)
                print(f"  ok    {key}: {info['database']} as {info['user']}")
            except Exception as exc:
                print(f"  FAIL  {key}: {type(exc).__name__}: {str(exc)[:120]}")
                sys.exit(1)
except Exception as exc:
    print(f"  FAIL  pool: {type(exc).__name__}: {str(exc)[:160]}")
    sys.exit(1)
PY
[[ $? -ne 0 ]] && failures=$((failures + 1))

echo
if [[ $failures -eq 0 ]]; then
  echo "All checks passed."
else
  echo "$failures check(s) failed."
  exit 1
fi
