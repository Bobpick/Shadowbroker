#!/usr/bin/env bash
# Full reset for US Game Theory / Protest Watch (Docker, build from source).
#
# Usage:
#   ./reset-us-gt.sh              # rebuild + restart, keep data volume
#   ./reset-us-gt.sh --wipe-data  # also drop backend_data volume (hard reset)
#   ./reset-us-gt.sh --no-build   # restart only (use existing local images)
#
# After start: enables gt_risk layer, refreshes GT from Reddit/Telegram feeds,
# and prints verification for /api/live-data/slow us_cities.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.build.yml)
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-3050}"
WIPE_DATA=0
NO_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --wipe-data) WIPE_DATA=1 ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "[!] Unknown arg: $arg" >&2
      exit 1
      ;;
  esac
done

log() { printf '[*] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*"; }
die() { printf '[!] ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_cmd docker
require_cmd curl
docker compose version >/dev/null 2>&1 || die "docker compose plugin required"

ensure_env() {
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      log "Created .env from .env.example"
    else
      touch .env
      log "Created empty .env"
    fi
  fi

  set_kv() {
    local key="$1" val="$2"
    if grep -qE "^[# ]*${key}=" .env 2>/dev/null; then
      sed -i -E "s|^[# ]*${key}=.*|${key}=${val}|" .env
    else
      printf '\n%s=%s\n' "$key" "$val" >> .env
    fi
  }

  # US Protest Watch depends on GT + Reddit (and Telegram when available).
  set_kv GT_ANALYTICS_ENABLED true
  set_kv REDDIT_OSINT_ENABLED true
  set_kv TELEGRAM_OSINT_ENABLED true
  set_kv BACKEND_PORT "$BACKEND_PORT"
  set_kv FRONTEND_PORT "$FRONTEND_PORT"

  log "Ensured GT_ANALYTICS_ENABLED=true, Reddit/Telegram OSINT on, ports ${FRONTEND_PORT}/${BACKEND_PORT}"
}

stop_stack() {
  log "Stopping ShadowBroker containers..."
  "${COMPOSE[@]}" down --remove-orphans || true
  if [[ "$WIPE_DATA" -eq 1 ]]; then
    warn "Wiping Docker volumes (backend_data)..."
    "${COMPOSE[@]}" down -v --remove-orphans || true
  fi
}

build_and_start() {
  if [[ "$NO_BUILD" -eq 1 ]]; then
    log "Starting with existing images (--no-build)..."
    "${COMPOSE[@]}" up -d
  else
    log "Building backend + frontend from local source..."
    "${COMPOSE[@]}" build
    log "Starting stack..."
    "${COMPOSE[@]}" up -d
  fi
}

wait_healthy() {
  local url="http://127.0.0.1:${BACKEND_PORT}/api/health"
  log "Waiting for backend health on :${BACKEND_PORT}..."
  for i in $(seq 1 90); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      log "Backend is responding"
      return 0
    fi
    sleep 2
  done
  die "Backend did not become healthy in time. Try: ${COMPOSE[*]} logs -f backend"
}

enable_and_refresh_gt() {
  log "Enabling gt_risk layer on the live uvicorn process..."
  # Must go through HTTP inside the container — docker exec python does not share
  # the in-memory active_layers of the API process.
  docker exec shadowbroker-backend curl -fsS -X POST http://127.0.0.1:8000/api/layers \
    -H 'Content-Type: application/json' \
    -d '{"layers":{"gt_risk":true,"reddit_osint":true,"telegram_osint":true}}' \
    >/dev/null

  log "Refreshing GT snapshot from current Reddit/Telegram feeds..."
  docker exec shadowbroker-backend curl -fsS -X POST http://127.0.0.1:8000/api/analytics/risk_heatmap \
    -H 'Content-Type: application/json' \
    -d '{"refresh":true}' \
    >/dev/null 2>&1 || warn "risk_heatmap refresh optional (continuing)"
}

verify() {
  local base="http://127.0.0.1:${BACKEND_PORT}"
  log "Verifying API..."

  echo "--- /api/analytics/us_cities (direct) ---"
  curl -fsS "${base}/api/analytics/us_cities" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('enabled', d.get('enabled'), 'active_metros', d.get('active_metros'), 'cities', len(d.get('cities') or []))
for c in (d.get('cities') or [])[:5]:
    print(' ', c.get('label'), 'potential', c.get('protest_potential'), 'hits', c.get('protest_mentions'))
" || warn "us_cities check failed"

  echo "--- /api/live-data/slow gt_risk (what the UI polls) ---"
  curl -fsS "${base}/api/live-data/slow" | python3 -c "
import sys, json
d = json.load(sys.stdin)
gt = d.get('gt_risk') or {}
uc = gt.get('us_cities') or {}
print('gt_risk.enabled', gt.get('enabled'))
print('us_cities.active_metros', uc.get('active_metros'))
print('us_cities.count', len(uc.get('cities') or []))
if not gt.get('enabled'):
    print('PROBLEM: gt_risk is disabled on slow feed — US panel will not show.')
    sys.exit(2)
" || warn "slow feed check failed"

  log "Dashboard: http://127.0.0.1:${FRONTEND_PORT}"
  log "Toggle layer: Game Theory / gt_risk ON in the left panel if the HUD is still hidden."
  log "Hard-refresh the browser (Ctrl+Shift+R) after reset."
}

main() {
  log "=== US Game Theory full reset ==="
  ensure_env
  stop_stack
  build_and_start
  wait_healthy
  # Give fetchers a moment after health
  sleep 5
  enable_and_refresh_gt
  verify
  log "Done."
}

main "$@"
