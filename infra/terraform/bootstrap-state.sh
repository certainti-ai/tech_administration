#!/usr/bin/env bash
# Create the Azure Storage account that holds Terraform state, then print the
# `terraform init` line that uses it.
#
#   bash infra/terraform/bootstrap-state.sh
#
# Why this exists, and why it is not Terraform: the state has to exist before
# Terraform can keep state, so something has to create it out of band. This
# talks to ARM directly with the service principal already in ARM_*.
#
# Why remote state at all — this configuration generates the VM's SSH private
# key and writes it to Key Vault, so **the state file is itself a secret**
# (SECURITY.md). Local state in an ephemeral container is worse than
# inconvenient: when the container is reclaimed, the VM still exists and nothing
# can manage or destroy it. That is how infrastructure gets orphaned and billed
# forever.
#
# Idempotent: re-running reports what already exists and changes nothing.

set -Eeuo pipefail

: "${ARM_SUBSCRIPTION_ID:?not set}"
: "${ARM_TENANT_ID:?not set}"
: "${ARM_CLIENT_ID:?not set}"
: "${ARM_CLIENT_SECRET:?not set}"

LOCATION=${LOCATION:-centralus}
STATE_RG=${STATE_RG:-trd365-tfstate}
CONTAINER=${CONTAINER:-tfstate}
STATE_KEY=${STATE_KEY:-maintenance-vm.tfstate}

# Storage account names are globally unique, 3-24 lowercase alphanumerics. Derive
# the suffix from the subscription so the same subscription always lands on the
# same name and re-running finds the account it made last time.
SUFFIX=$(printf '%s' "$ARM_SUBSCRIPTION_ID" | sha256sum | cut -c1-8)
ACCOUNT=${ACCOUNT:-trd365tfstate$SUFFIX}

API_RG=2021-04-01
API_ST=2023-01-01

log() { printf '[bootstrap] %s\n' "$*"; }
fail() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

TOKEN=$(curl -s --max-time 30 -X POST \
  "https://login.microsoftonline.com/${ARM_TENANT_ID}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${ARM_CLIENT_ID}" \
  --data-urlencode "client_secret=${ARM_CLIENT_SECRET}" \
  -d 'scope=https%3A%2F%2Fmanagement.azure.com%2F.default' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
[[ -n "$TOKEN" ]] || fail "could not obtain an ARM token; check the ARM_* values"

arm() { # arm METHOD PATH [BODY]
  local method=$1 path=$2 body=${3:-}
  if [[ -n "$body" ]]; then
    curl -s -X "$method" -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" -d "$body" \
      "https://management.azure.com${path}"
  else
    curl -s -X "$method" -H "Authorization: Bearer $TOKEN" \
      "https://management.azure.com${path}"
  fi
}

BASE="/subscriptions/${ARM_SUBSCRIPTION_ID}"

# ------------------------------------------------------------- resource group

log "resource group $STATE_RG in $LOCATION"
arm PUT "${BASE}/resourcegroups/${STATE_RG}?api-version=${API_RG}" \
  "{\"location\":\"${LOCATION}\",\"tags\":{\"purpose\":\"terraform-state\",\"project\":\"trd365-maintenance\"}}" \
  >/dev/null

# ----------------------------------------------------------- storage account

log "storage account $ACCOUNT"
existing=$(arm GET "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}?api-version=${API_ST}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)

if [[ -n "$existing" ]]; then
  log "  already exists"
else
  # No public blob access, TLS 1.2 floor, and versioning on: state is a secret,
  # and a corrupted or truncated write should be recoverable.
  arm PUT "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}?api-version=${API_ST}" '{
    "location": "'"${LOCATION}"'",
    "sku": {"name": "Standard_LRS"},
    "kind": "StorageV2",
    "properties": {
      "allowBlobPublicAccess": false,
      "minimumTlsVersion": "TLS1_2",
      "supportsHttpsTrafficOnly": true,
      "allowSharedKeyAccess": true
    },
    "tags": {"purpose": "terraform-state", "project": "trd365-maintenance"}
  }' >/dev/null

  log "  waiting for provisioning"
  for _ in $(seq 1 40); do
    state=$(arm GET "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}?api-version=${API_ST}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("properties",{}).get("provisioningState",""))' 2>/dev/null || true)
    [[ "$state" == "Succeeded" ]] && break
    sleep 5
  done
  [[ "$state" == "Succeeded" ]] || fail "storage account did not provision (last state: ${state:-unknown})"
fi

# Blob versioning, so a bad state write can be rolled back.
arm PATCH "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}/blobServices/default?api-version=${API_ST}" \
  '{"properties":{"isVersioningEnabled":true}}' >/dev/null || log "  (versioning not set; not fatal)"

log "container $CONTAINER"
arm PUT "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}/blobServices/default/containers/${CONTAINER}?api-version=${API_ST}" \
  '{"properties":{"publicAccess":"None"}}' >/dev/null

# --------------------------------------------------------------- access key

KEY=$(arm POST "${BASE}/resourceGroups/${STATE_RG}/providers/Microsoft.Storage/storageAccounts/${ACCOUNT}/listKeys?api-version=${API_ST}" '{}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["keys"][0]["value"])' 2>/dev/null || true)
[[ -n "$KEY" ]] || fail "could not read the storage account key"

cat <<EOF

[bootstrap] done.

  resource group   : $STATE_RG
  storage account  : $ACCOUNT
  container        : $CONTAINER
  state file       : $STATE_KEY

Initialise Terraform against it — the key is exported rather than passed on the
command line so it stays out of your shell history:

  export ARM_ACCESS_KEY='<the key — printed below once>'
  terraform init \\
    -backend-config="resource_group_name=$STATE_RG" \\
    -backend-config="storage_account_name=$ACCOUNT" \\
    -backend-config="container_name=$CONTAINER" \\
    -backend-config="key=$STATE_KEY"

EOF
printf 'ARM_ACCESS_KEY=%s\n' "$KEY"
