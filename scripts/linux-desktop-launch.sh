#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
START_SCRIPT="$SCRIPT_DIR/start-source.sh"
LOG_DIR="$REPO_ROOT/.local/logs"
LOG_FILE="$LOG_DIR/shadowbroker-source.log"
PID_FILE="$LOG_DIR/shadowbroker-source.pid"
DASHBOARD_URL="http://127.0.0.1:3000"

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "$1" "$2" 2>/dev/null || true
  fi
}

is_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tln | grep -q ":${port} "
    return
  fi
  curl -fsS -o /dev/null "http://127.0.0.1:${port}/" 2>/dev/null
}

source_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  is_listening 3000 && is_listening 8000
}

start_source() {
  mkdir -p "$LOG_DIR"
  if source_running; then
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    notify "ShadowBroker" "npm/Node.js is required for source mode."
    exit 1
  fi
  if ! command -v python3.12 >/dev/null 2>&1 && ! command -v python3.11 >/dev/null 2>&1; then
    notify "ShadowBroker" "Python 3.11 or 3.12 is required for source mode."
    exit 1
  fi
  nohup "$START_SCRIPT" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
}

cd "$REPO_ROOT"
start_source

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