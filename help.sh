#!/usr/bin/env bash
# ShadowBroker Full Clean Install - Docker reset + fresh repo + port 3000 + BUILD FROM SOURCE
# Complete self-contained version
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

# ====================== 1. FULL DOCKER NUKE (uninstall) ======================
uninstall_docker() {
  warn "=== FULL DOCKER RESET (this will delete ALL containers, images, volumes) ==="
  sudo systemctl stop docker.socket docker.service containerd 2>/dev/null || true

  sudo apt-get purge -y \
    docker-engine docker docker.io docker-ce docker-ce-cli \
    docker-compose-plugin docker-compose containerd containerd.io runc \
    docker-buildx-plugin 2>/dev/null || true

  sudo rm -rf \
    /var/lib/docker \
    /var/lib/containerd \
    /var/run/docker \
    /etc/docker \
    ~/.docker \
    /etc/apt/sources.list.d/docker.list \
    /etc/apt/keyrings/docker.gpg 2>/dev/null || true

  sudo apt-get autoremove -y 2>/dev/null || true
  sudo apt-get autoclean -y 2>/dev/null || true

  log "Docker packages and data removed."
}

# ====================== 2. REINSTALL DOCKER (official repo) ======================
reinstall_docker() {
  log "Installing Docker from official repository..."

  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg lsb-release

  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

  sudo apt-get update -y

  sudo apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

  sudo systemctl enable --now docker

  # Add current user to docker group
  if ! id -nG "$USER" | grep -qw docker; then
    sudo usermod -aG docker "$USER"
    warn "Added $USER to docker group. You may need to run 'newgrp docker' or log out/in."
  fi

  # Verify
  docker --version || die "Docker installation verification failed."
  docker compose version || die "Docker Compose plugin not found."

  log "Docker reinstalled successfully."
}

# ====================== 3. CLONE / RESET REPO ======================
setup_repo() {
  log "Setting up ShadowBroker from $REPO_URL ..."

  if [[ -d "$REPO_DIR/.git" ]]; then
    warn "Existing git repo found — hard resetting to origin/main."
    cd "$REPO_DIR"
    git fetch origin main || warn "git fetch had issues (continuing)"
    git reset --hard origin/main || die "git reset failed. Try: rm -rf $REPO_DIR && re-run."
    git clean -fdx || warn "git clean finished with warnings."
  else
    if [[ -d "$REPO_DIR" ]]; then
      warn "$REPO_DIR exists but is not a git repo — removing it."
      rm -rf "$REPO_DIR"
    fi
    log "Cloning fresh repository..."
    git clone "$REPO_URL" "$REPO_DIR" || die "git clone failed."
    cd "$REPO_DIR"
  fi

  git checkout main 2>/dev/null || git checkout -b main || true
  find . -name "*.sh" -type f -exec chmod +x {} + 2>/dev/null || true

  log "Repository ready at $(pwd) on branch: $(git branch --show-current 2>/dev/null || echo 'unknown')"
}

# ====================== 4. CONFIGURE .env + START (BUILD FROM SOURCE) ======================
start_shadowbroker() {
  log "Configuring for frontend port $FRONTEND_PORT ..."

  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      log "Created .env from .env.example"
    else
      touch .env
      warn "No .env.example found — created empty .env"
    fi
  fi

  if grep -q "^FRONTEND_PORT=" .env; then
    sed -i "s/^FRONTEND_PORT=.*/FRONTEND_PORT=$FRONTEND_PORT/" .env
  else
    echo "FRONTEND_PORT=$FRONTEND_PORT" >> .env
  fi

  if ! grep -q "^BACKEND_MEMORY_LIMIT=" .env; then
    echo "BACKEND_MEMORY_LIMIT=8G" >> .env
    log "Set BACKEND_MEMORY_LIMIT=8G"
  fi

  log "Building images from YOUR source (using docker-compose.build.yml)..."
  docker compose -f docker-compose.yml -f docker-compose.build.yml build --no-cache || \
    die "Build failed. Check the docker output above."

  log "Starting ShadowBroker..."
  docker compose -f docker-compose.yml -f docker-compose.build.yml up -d || die "docker compose up failed."

  log "Waiting for dashboard to respond..."
  for i in {1..90}; do
    if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$FRONTEND_PORT" 2>/dev/null; then
      echo ""
      log "✅ ShadowBroker is running!"
      log " → Open: http://localhost:$FRONTEND_PORT"
      return 0
    fi
    printf '.'
    sleep 3
  done

  echo ""
  warn "Dashboard not ready in time."
  warn "Check: docker compose -f docker-compose.yml -f docker-compose.build.yml logs -f backend"
}

main() {
  log "=== ShadowBroker Full Clean Install (Docker nuke + fresh build from your fork) ==="
  warn "This will DELETE all existing Docker containers, images, and data."

  require_cmd git
  require_cmd curl

  uninstall_docker
  reinstall_docker

  # Try to activate docker group in current shell
  if command -v newgrp >/dev/null 2>&1; then
    sg docker -c "true" 2>/dev/null || true
  fi

  setup_repo
  start_shadowbroker

  log "All done!"
  log "Dashboard: http://localhost:3000"
  log "Future updates: cd Shadowbroker && git pull && docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build"
}

main "$@"
