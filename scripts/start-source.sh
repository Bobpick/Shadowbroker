#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export BACKEND_BASE_PYTHON="${BACKEND_BASE_PYTHON:-python3.12}"
export BACKEND_RELOAD="${BACKEND_RELOAD:-}"

"$SCRIPT_DIR/sync-backend-env.sh"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^shadowbroker-'; then
  echo "[*] Stopping Docker ShadowBroker containers to free ports 3000/3050..."
  (cd "$REPO_ROOT" && docker compose stop) || true
fi

cd "$REPO_ROOT"
exec ./start.sh