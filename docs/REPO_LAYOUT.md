# Repository layout

Root is intentionally thin: **run/compose entry points**, **license/readme**, and **docker-compose**. Operator tools and install guides live under folders.

## Stay at repository root

| Path | Why |
|------|-----|
| `README.md`, `LICENSE`, `CONTRIBUTING.md`, `DATA-ATTRIBUTION.md` | Project identity |
| `docker-compose*.yml` | Standard `docker compose` from clone root |
| `start.sh` / `start.bat` / `stop.bat` | Documented one-click launchers |
| `compose.sh` | Compose engine wrapper (Docker/Podman) |
| `Makefile`, `pyproject.toml`, `uv.lock` | Build tooling |
| `backend/`, `frontend/`, `scripts/`, `docs/` | Source trees |

Thin **compat wrappers** also remain at root so old habits still work:

- `./quick_restart.sh` → `scripts/operator/quick_restart.sh`
- `./nuke.sh` → `scripts/operator/nuke.sh`

## `docs/`

| Path | Contents |
|------|----------|
| `docs/install/macbook_install.md` | MacBook + Ollama + daily/weekly briefs |
| `docs/install/WINDOWS_INSTALL.txt` | Windows install notes |
| `docs/Mesh.md` | Mesh / InfoNet overview |
| `docs/mesh/` | Mesh ops runbooks |
| `docs/REPO_LAYOUT.md` | This file |
| `docs/help.txt` | Short help blurb |

## `scripts/`

| Path | Contents |
|------|----------|
| `scripts/daily_24h_brief.py` | PAT Labs daily brief |
| `scripts/weekly_intel_brief.py` | Weekly issues synopsis |
| `scripts/run_*.sh` | Cron/launchd wrappers |
| `scripts/operator/` | Operator recovery, wormhole, meshnode, GT reset |
| `scripts/mesh/` | Mesh tooling |

## Prefer not at root

- Large zips (`ShadowBroker-Windows.zip`) — better as GitHub **Releases** assets  
- Nested full clones (`Shadowbroker/`) — local only, should not be committed  
- Runtime data (`.env`, caches) — gitignored  

## Invoke after this layout

```bash
# Daily / weekly briefs
./scripts/run_daily_24h_brief.sh
./scripts/run_weekly_intel_brief.sh

# Recovery
./quick_restart.sh          # or: ./scripts/operator/quick_restart.sh
./nuke.sh                   # or: ./scripts/operator/nuke.sh

# Docker
docker compose up -d
./start.sh
```
