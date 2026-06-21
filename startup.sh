#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
ENV_FILE="$REPO_ROOT/.env"

COMPOSE_PROJECT_NAME="shadowbroker"
FRONTEND_PORT=3000

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE" 2>/dev/null || true

  [[ -n "${FRONTEND_PORT:-}" ]] && FRONTEND_PORT="$FRONTEND_PORT"
  [[ -n "${COMPOSE_PROJECT_NAME:-}" ]] && COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME"
fi

DASHBOARD_URL="http://127.0.0.1:${FRONTEND_PORT}"

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "$1" "$2" 2>/dev/null || true
  fi
}

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  notify "ShadowBroker" "Docker is not running."
  exit 1
fi

cd "$REPO_ROOT"

echo "Starting ShadowBroker..."
if ! docker compose -p "$COMPOSE_PROJECT_NAME" up -d; then
  notify "ShadowBroker" "Failed to start containers."
  exit 1
fi

# Wait for frontend to be ready
ready=0
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$DASHBOARD_URL" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  notify "ShadowBroker" "Dashboard did not become ready."
  exit 1
fi

# Open in browser
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
fi

echo "ShadowBroker is running → $DASHBOARD_URL"
