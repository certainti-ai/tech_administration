#!/usr/bin/env bash
# Can this session actually deploy? Separates "bad credentials" from "no route".
#
#   bash tools/check_azure_reachability.sh
#
# Deployment has stalled twice on a wrong diagnosis, so this measures rather than
# reasons. It obtains a real token from the service principal in ARM_*, then uses
# that token against Azure Resource Manager. Those two steps fail for completely
# different reasons, and the fixes have nothing in common:
#
#   token fails       -> the credentials are wrong or expired. Rotate them.
#   token ok, ARM fails -> the credentials are fine and the environment has no
#                        route to ARM. No credential change helps; the
#                        environment's Network access level is the thing.
#                        See docs/HANDOFF.md §10.
#
# Read-only. It lists resource groups and creates nothing.

set -uo pipefail

pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; }

echo "== credentials present =="
missing=0
for var in ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET ARM_SUBSCRIPTION_ID; do
  if [[ -n "${!var:-}" ]]; then
    pass "$var is set"
  else
    bad "$var is NOT set"
    missing=1
  fi
done
[[ $missing -eq 0 ]] || { echo; bad "cannot continue without all four"; exit 1; }

echo
echo "== can we mint a token? (login.microsoftonline.com) =="
response=$(curl -s --max-time 25 -X POST \
  "https://login.microsoftonline.com/${ARM_TENANT_ID}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${ARM_CLIENT_ID}" \
  --data-urlencode "client_secret=${ARM_CLIENT_SECRET}" \
  -d "scope=https%3A%2F%2Fmanagement.azure.com%2F.default" 2>&1)

token=$(printf '%s' "$response" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)

if [[ -z "$token" ]]; then
  bad "no token returned"
  printf '%s\n' "$response" | head -c 400 | sed 's/^/        /'
  echo
  echo "The credentials are the problem, not the network. Rotate or re-issue them."
  exit 1
fi
pass "token acquired (${#token} chars) — the service principal is valid"

echo
echo "== can we reach ARM with it? (management.azure.com) =="
body=$(mktemp)
code=$(curl -s -o "$body" -w '%{http_code}' --max-time 25 \
  -H "Authorization: Bearer ${token}" \
  "https://management.azure.com/subscriptions/${ARM_SUBSCRIPTION_ID}/resourcegroups?api-version=2021-04-01" \
  2>/dev/null)
status=$?

case "$code" in
  200)
    count=$(python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("value",[])))' \
      <"$body" 2>/dev/null || echo "?")
    pass "ARM answered 200 — $count resource group(s) visible"
    echo
    echo "This session CAN deploy. From infra/terraform: terraform init && terraform apply"
    ;;
  401|403)
    warn "ARM answered $code — reachable, but this principal is not authorised"
    head -c 400 "$body" | sed 's/^/        /'
    echo
    echo "A role assignment problem, not a network one. The principal needs"
    echo "Contributor on the subscription."
    ;;
  000)
    bad "no HTTP response at all (curl exit $status)"
    echo
    echo "The token above proves the credentials are good, so this is the network:"
    echo "the gateway refuses CONNECT to management.azure.com for this environment."
    echo "Nothing in this repository can change that. The environment's Network"
    echo "access level has to allow the host — see docs/HANDOFF.md §10."
    echo
    echo "Proxy's own account of recent refusals:"
    curl -sS "${HTTPS_PROXY:-}/__agentproxy/status" 2>/dev/null \
      | python3 -c '
import sys, json
try:
    failures = json.load(sys.stdin).get("recentRelayFailures", [])
except Exception:
    sys.exit(0)
seen = set()
for entry in failures:
    host = entry.get("host", "?")
    if host in seen:
        continue
    seen.add(host)
    print("        " + host + ": " + entry.get("detail", "?"))
' 2>/dev/null || echo "        (proxy status unavailable)"
    ;;
  *)
    warn "ARM answered $code"
    head -c 400 "$body" | sed 's/^/        /'
    ;;
esac
rm -f "$body"

echo
echo "== other hosts a deploy needs =="
for host in registry.terraform.io vault.azure.net graph.microsoft.com; do
  hostcode=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "https://$host/" 2>/dev/null)
  if [[ "$hostcode" == "000" ]]; then
    bad "$host unreachable"
  else
    pass "$host reachable (HTTP $hostcode)"
  fi
done
