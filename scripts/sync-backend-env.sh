#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_ENV="$REPO_ROOT/.env"
BACKEND_ENV="$REPO_ROOT/backend/.env"
EXAMPLE="$REPO_ROOT/backend/.env.example"

if [[ ! -f "$BACKEND_ENV" && -f "$EXAMPLE" ]]; then
  cp "$EXAMPLE" "$BACKEND_ENV"
fi

touch "$BACKEND_ENV"

if [[ -f "$ROOT_ENV" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Z0-9_]+$ ]] || continue
    [[ "$key" == "FRONTEND_PORT" || "$key" == "BACKEND_PORT" || "$key" == "BIND" || "$key" == "BACKEND_MEMORY_LIMIT" ]] && continue
    value="${line#*=}"
    if grep -q "^${key}=" "$BACKEND_ENV"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$BACKEND_ENV"
    else
      printf '%s=%s\n' "$key" "$value" >>"$BACKEND_ENV"
    fi
  done <"$ROOT_ENV"
fi

set_kv() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$BACKEND_ENV"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$BACKEND_ENV"
  else
    printf '%s=%s\n' "$key" "$value" >>"$BACKEND_ENV"
  fi
}

# Source-run defaults for layers Docker images often ship without.
set_kv "GT_ANALYTICS_ENABLED" "${GT_ANALYTICS_ENABLED:-true}"
set_kv "REDDIT_OSINT_ENABLED" "${REDDIT_OSINT_ENABLED:-true}"
set_kv "TELEGRAM_OSINT_ENABLED" "${TELEGRAM_OSINT_ENABLED:-true}"
set_kv "NEWS_ENABLED" "${NEWS_ENABLED:-true}"
set_kv "PREDICTION_MARKETS_ENABLED" "${PREDICTION_MARKETS_ENABLED:-false}"
set_kv "FINANCIAL_ENABLED" "${FINANCIAL_ENABLED:-false}"
set_kv "CROWDTHREAT_ENABLED" "${CROWDTHREAT_ENABLED:-false}"
set_kv "FIMI_ENABLED" "${FIMI_ENABLED:-false}"
set_kv "NUFORC_ENABLED" "${NUFORC_ENABLED:-false}"

echo "Synced environment to $BACKEND_ENV"