#!/usr/bin/env bash
# Nuclear option: stop stack, reinstall from YOUR git repo (clean working tree),
# rebuild images from local source, start fresh.
#
# PRESERVES: .env (copied aside and restored)
# DESTROYS:  containers, optional named volumes, uncommitted local files (via git clean)
#
# BEFORE RUNNING: commit/push anything you care about (see quick check below).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

REPO_URL_DEFAULT="https://github.com/Bobpick/Shadowbroker.git"
FRONTEND_PORT_DEFAULT=3000

log() { printf '[nuke] %s\n' "$*"; }
warn() { printf '[nuke] ! %s\n' "$*" >&2; }
die() { printf '[nuke] ERROR: %s\n' "$*" >&2; exit 1; }

confirm() {
  local prompt="${1:-Continue? [y/N]} "
  if [[ "${NUKE_YES:-}" == "1" || "${1:-}" == "-y" ]]; then
    return 0
  fi
  read -r -p "$prompt" ans
  [[ "$ans" == "y" || "$ans" == "Y" || "$ans" == "yes" ]]
}

# ── Safety: refuse if dirty unless forced ───────────────────────────────────
log "Checking for uncommitted work in $ROOT …"
if [[ -d .git ]]; then
  dirty="$(git status --porcelain 2>/dev/null || true)"
  if [[ -n "$dirty" && "${NUKE_FORCE_DIRTY:-}" != "1" ]]; then
    warn "Uncommitted changes detected:"
    git status --short || true
    warn ""
    warn "Commit and push these first, or re-run with:"
    warn "  NUKE_FORCE_DIRTY=1 ./nuke.sh"
    die "refusing to nuke a dirty tree"
  fi
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  log "Branch: $branch"
  log "HEAD:   $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    git fetch origin 2>/dev/null || warn "git fetch failed (offline?)"
    ahead="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
    if [[ "${ahead:-0}" -gt 0 && "${NUKE_FORCE_DIRTY:-}" != "1" ]]; then
      warn "You have $ahead local commit(s) not pushed to origin."
      warn "Push first: git push -u origin HEAD"
      die "refusing to nuke with unpushed commits"
    fi
  fi
else
  warn "Not a git checkout — will clone into place if needed."
fi

if [[ "${1:-}" != "-y" && "${NUKE_YES:-}" != "1" ]]; then
  echo ""
  echo "This will:"
  echo "  • docker compose down -v (containers + compose volumes)"
  echo "  • git fetch + hard reset to origin/main (or current upstream)"
  echo "  • git clean -fdx (except .env backup)"
  echo "  • rebuild images from local source (no-cache)"
  echo "  • start the stack"
  echo ""
  confirm "Type y to NUKE and reinstall: " || die "aborted"
fi

command -v docker >/dev/null 2>&1 || die "docker not found"
command -v git >/dev/null 2>&1 || die "git not found"

COMPOSE=(docker compose -f docker-compose.yml)
[[ -f docker-compose.build.yml ]] && COMPOSE+=(-f docker-compose.build.yml)
[[ -f docker-compose.override.yml ]] && COMPOSE+=(-f docker-compose.override.yml)

# ── Preserve .env ───────────────────────────────────────────────────────────
ENV_BAK=""
if [[ -f .env ]]; then
  ENV_BAK="$(mktemp /tmp/shadowbroker.env.XXXXXX)"
  cp -a .env "$ENV_BAK"
  log "Saved .env → $ENV_BAK"
fi

# ── Stop everything ─────────────────────────────────────────────────────────
log "Stopping compose stack and removing volumes…"
"${COMPOSE[@]}" down -v --remove-orphans 2>/dev/null || true
docker ps -aq --filter name=shadowbroker 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true

# ── Reset tree from remote ──────────────────────────────────────────────────
if [[ -d .git ]]; then
  remote_branch="main"
  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    remote_branch="$(git rev-parse --abbrev-ref '@{u}')"
  else
    remote_branch="origin/main"
  fi
  log "Fetching and hard-resetting to $remote_branch …"
  git fetch origin || warn "fetch failed — resetting to last known remote ref"
  if git show-ref --verify --quiet "refs/remotes/origin/main"; then
    git checkout main 2>/dev/null || git checkout -B main origin/main
    git reset --hard origin/main
  else
    git reset --hard "$remote_branch" || die "git reset failed"
  fi
  # Keep scripts executable; clean everything else including ignored build junk
  log "git clean -fdx (worktree wipe)…"
  git clean -fdx -e .env -e "$ENV_BAK" 2>/dev/null || git clean -fdx
else
  parent="$(dirname "$ROOT")"
  name="$(basename "$ROOT")"
  log "Cloning $REPO_URL_DEFAULT into $parent/$name …"
  cd "$parent"
  rm -rf "$name"
  git clone "$REPO_URL_DEFAULT" "$name"
  cd "$name"
  ROOT="$(pwd)"
fi

# Restore .env
if [[ -n "$ENV_BAK" && -f "$ENV_BAK" ]]; then
  cp -a "$ENV_BAK" "$ROOT/.env"
  log "Restored .env"
  rm -f "$ENV_BAK"
elif [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  log "Created .env from .env.example"
fi

# Ports / memory defaults
if [[ -f .env ]]; then
  if grep -q '^FRONTEND_PORT=' .env; then
    sed -i "s/^FRONTEND_PORT=.*/FRONTEND_PORT=${FRONTEND_PORT_DEFAULT}/" .env
  else
    echo "FRONTEND_PORT=${FRONTEND_PORT_DEFAULT}" >> .env
  fi
  if ! grep -q '^BACKEND_MEMORY_LIMIT=' .env; then
    echo "BACKEND_MEMORY_LIMIT=8G" >> .env
  fi
  if ! grep -q '^HOST_UID=' .env; then
    echo "HOST_UID=$(id -u)" >> .env
    echo "HOST_GID=$(id -g)" >> .env
  fi
fi

chmod +x ./*.sh scripts/*.sh 2>/dev/null || true

# ── Rebuild from source ─────────────────────────────────────────────────────
cd "$ROOT"
COMPOSE=(docker compose -f docker-compose.yml)
[[ -f docker-compose.build.yml ]] && COMPOSE+=(-f docker-compose.build.yml)
[[ -f docker-compose.override.yml ]] && COMPOSE+=(-f docker-compose.override.yml)

if [[ -f docker-compose.build.yml ]]; then
  log "Building images from local source (no cache)…"
  "${COMPOSE[@]}" build --no-cache
else
  log "No docker-compose.build.yml — pulling images…"
  "${COMPOSE[@]}" pull || true
fi

log "Starting stack…"
"${COMPOSE[@]}" up -d

FRONTEND_PORT="${FRONTEND_PORT_DEFAULT}"
[[ -f .env ]] && FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' .env | head -1 | cut -d= -f2- || echo "$FRONTEND_PORT_DEFAULT")"
BACKEND_PORT=3050
[[ -f .env ]] && BACKEND_PORT="$(grep -E '^BACKEND_PORT=' .env | head -1 | cut -d= -f2- || echo 3050)"
BACKEND_PORT="${BACKEND_PORT:-3050}"

log "Waiting for health…"
for i in $(seq 1 90); do
  if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${BACKEND_PORT}/api/health" 2>/dev/null \
    && curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/" 2>/dev/null; then
    log "✅ Shadowbroker is up"
    log "   Dashboard: http://127.0.0.1:${FRONTEND_PORT}"
    log "   API:       http://127.0.0.1:${BACKEND_PORT}/api/health"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 3
done

warn "Started but health check timed out — check logs:"
warn "  cd $ROOT && docker compose logs --tail=100"
exit 1
