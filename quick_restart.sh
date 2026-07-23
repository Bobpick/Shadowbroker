#!/usr/bin/env bash
# Quick recovery when Shadowbroker will not load (containers hung / OOM / dead).
# Does NOT reinstall or wipe data — only bounce compose stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

log() { printf '[quick_restart] %s\n' "$*"; }
warn() { printf '[quick_restart] ! %s\n' "$*" >&2; }

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found" >&2
  exit 1
fi

if [[ ! -f docker-compose.yml ]]; then
  echo "Missing docker-compose.yml in $ROOT" >&2
  exit 1
fi

# Prefer build override when present (local source), else stock compose.
COMPOSE=(docker compose -f docker-compose.yml)
if [[ -f docker-compose.build.yml ]]; then
  COMPOSE+=(-f docker-compose.build.yml)
fi
if [[ -f docker-compose.override.yml ]]; then
  COMPOSE+=(-f docker-compose.override.yml)
fi

FRONTEND_PORT="${FRONTEND_PORT:-}"
BACKEND_PORT="${BACKEND_PORT:-}"
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  # Only pull simple KEY=VAL lines we need
  FRONTEND_PORT="${FRONTEND_PORT:-$(grep -E '^FRONTEND_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)}"
  BACKEND_PORT="${BACKEND_PORT:-$(grep -E '^BACKEND_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)}"
  set +a
fi
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-3050}"

log "Stopping stack (preserving volumes)…"
"${COMPOSE[@]}" down --remove-orphans || true

log "Removing orphaned shadowbroker containers if any…"
docker ps -aq --filter name=shadowbroker 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true

# Host processes (e.g. leftover next-server) can steal 3000/3050 from Docker
free_port() {
  local port="$1"
  local pids=""
  if command -v fuser >/dev/null 2>&1; then
    pids="$(fuser "${port}/tcp" 2>/dev/null || true)"
  fi
  if [[ -z "${pids// /}" ]] && command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -t -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [[ -n "${pids// /}" ]]; then
    warn "Port ${port} in use by PID(s): $pids — stopping host listeners…"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}
free_port "$FRONTEND_PORT"
free_port "$BACKEND_PORT"

log "Starting stack…"
"${COMPOSE[@]}" up -d

log "Waiting for backend :$BACKEND_PORT and frontend :$FRONTEND_PORT …"
ok_be=0
ok_fe=0
for i in $(seq 1 60); do
  if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${BACKEND_PORT}/api/health" 2>/dev/null; then
    ok_be=1
  fi
  if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/" 2>/dev/null \
    || curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null; then
    ok_fe=1
  fi
  if [[ "$ok_be" -eq 1 && "$ok_fe" -eq 1 ]]; then
    log "OK — backend and frontend responding."
    log "  Dashboard: http://127.0.0.1:${FRONTEND_PORT}"
    log "  API:       http://127.0.0.1:${BACKEND_PORT}/api/health"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 3
done

warn "Timed out waiting for full health (be=$ok_be fe=$ok_fe)."
warn "Check: docker compose ps && docker compose logs --tail=80 backend frontend"
"${COMPOSE[@]}" ps || true
exit 1
