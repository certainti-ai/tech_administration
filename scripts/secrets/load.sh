# Load secrets from Azure Key Vault into the current shell.
#
#   source scripts/secrets/load.sh
#
# Must be sourced, not executed — a child process cannot export into its parent.
# Requires AZURE_KEY_VAULT_NAME and an Azure identity (see docs/secrets.md).

if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "load.sh must be sourced, not executed: source scripts/secrets/load.sh" >&2
  exit 1
fi

__certainti_secrets_dir() {
  if [ -n "${BASH_SOURCE[0]:-}" ]; then
    cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
  else
    # zsh and other shells that do not define BASH_SOURCE
    cd "$(dirname "${(%):-%x}")" 2>/dev/null && pwd
  fi
}

__certainti_load_secrets() {
  local dir output
  dir="$(__certainti_secrets_dir)" || return 1

  # Capture first so a failure does not eval a partial or error-shaped result.
  if ! output="$(node "${dir}/pull.mjs" --format shell "$@")"; then
    echo "Failed to load secrets from Key Vault. See the error above." >&2
    return 1
  fi

  eval "${output}"
  echo "Loaded $(printf '%s' "${output}" | grep -c '^export ') secret(s) into this shell." >&2
}

__certainti_load_secrets "$@"
