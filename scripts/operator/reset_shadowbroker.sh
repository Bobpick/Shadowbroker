#!/usr/bin/env bash
# ShadowBroker Full Clean Install - Docker reset + fresh repo + port 3000 + BUILD FROM SOURCE
set -euo pipefail

REPO_URL="https://github.com/Bobpick/Shadowbroker.git"
REPO_DIR="Shadowbroker"
FRONTEND_PORT=3000

log() { printf '[*] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*"; }
die() { printf '[!] ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

# ... (uninstall_docker and reinstall_docker functions unchanged) ...

# ====================== 3. CLONE / RESET REPO ======================
setup_repo() {
  log "Setting up ShadowBroker from $REPO_URL ..."

  if [[ -d "$REPO_DIR" ]]; then
    warn "Existing $REPO_DIR found — resetting it."
    cd "$REPO_DIR"
    git fetch origin main || true
    git reset --hard origin/main
    git clean -fdx
  else
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
  fi

  git checkout main 2>/dev/null || true
  chmod +x start.sh compose.sh scripts/*.sh scripts/operator/*.sh 2>/dev/null || true
}

# ====================== 4. CONFIGURE .env + START (BUILD FROM SOURCE) ======================
start_shadowbroker() {
  log "Configuring for frontend port $FRONTEND_PORT ..."

  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      log "Created .env from example"
    else
      touch .env
    fi
  fi

  # Force port 3000
  if grep -q "^FRONTEND_PORT=" .env; then
    sed -i "s/^FRONTEND_PORT=.*/FRONTEND_PORT=$FRONTEND_PORT/" .env
  else
    echo "FRONTEND_PORT=$FRONTEND_PORT" >> .env
  fi

  # Recommended: Give backend more memory for wastewater + heavy layers
  if ! grep -q "^BACKEND_MEMORY_LIMIT=" .env; then
    echo "BACKEND_MEMORY_LIMIT=8G" >> .env
    log "Set BACKEND_MEMORY_LIMIT=8G (increase if you have more RAM)"
  fi

  log "Building images from YOUR local source (Bobpick fork)..."
  # Use build override so it compiles backend/frontend from your code
  docker compose -f docker-compose.yml -f docker-compose.build.yml build --no-cache

  log "Starting ShadowBroker (built from source)..."
  docker compose -f docker-compose.yml -f docker-compose.build.yml up -d

  log "Waiting for dashboard..."
  for i in {1..90}; do
    if curl -fsS -o /dev/null "http://127.0.0.1:$FRONTEND_PORT" 2>/dev/null; then
      log "✅ ShadowBroker is running!"
      log "   → Open: http://localhost:$FRONTEND_PORT"
      return 0
    fi
    sleep 3
  done

  warn "Dashboard not ready yet. Check logs: docker compose logs -f backend"
}

main() {
  log "=== ShadowBroker Full Reset + Fresh Install (from YOUR repo) ==="

  uninstall_docker
  reinstall_docker
  setup_repo
  start_shadowbroker

  log "All done! Dashboard at http://localhost:3000"
  log "Images are now built from your Bobpick fork."
  log "Future updates: git pull && docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build"
}

main "$@"
