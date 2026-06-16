#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
FRONTEND_PORT=3000

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  port_from_env="$(grep -E '^[[:space:]]*FRONTEND_PORT=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '[:space:]"'"'"'')"
  if [[ -n "$port_from_env" ]]; then
    FRONTEND_PORT="$port_from_env"
  fi
fi

DASHBOARD_URL="http://127.0.0.1:${FRONTEND_PORT}"

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "$1" "$2" 2>/dev/null || true
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  notify "ShadowBroker" "Docker is not installed or not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  notify "ShadowBroker" "Docker is not running. Start Docker and try again."
  exit 1
fi

cd "$REPO_ROOT"
if ! docker compose up -d; then
  notify "ShadowBroker" "Failed to start containers. Check Docker logs."
  exit 1
fi

ready=0
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$DASHBOARD_URL" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  notify "ShadowBroker" "Dashboard did not become ready on ${DASHBOARD_URL}."
  exit 1
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
elif command -v google-chrome >/dev/null 2>&1; then
  google-chrome --new-window "$DASHBOARD_URL" >/dev/null 2>&1 &
elif command -v firefox >/dev/null 2>&1; then
  firefox --new-window "$DASHBOARD_URL" >/dev/null 2>&1 &
else
  notify "ShadowBroker" "No browser launcher found. Open ${DASHBOARD_URL} manually."
  exit 1
fi