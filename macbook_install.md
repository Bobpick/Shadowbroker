# MacBook Pro install — Shadowbroker + PAT Labs daily / weekly briefs

This guide installs the stack so a MacBook Pro can run **Shadowbroker** (data), **Ollama** (narrative), and the **PAT Labs** morning + weekly intelligence briefs.

---

## Architecture (three pieces)

| Piece | Role |
|--------|------|
| **Shadowbroker** (Docker) | Live OSINT feeds, GT/delta, wastewater, news |
| **Ollama + `olmo-3:32b-think`** | Local LLM for executive prose |
| **Python scripts** | Write fixed-name MD/HTML + rolling history JSON |

Outputs (default, fixed names — no dated archives):

```text
~/Desktop/Daily_Inspiration/shadowbroker_24h_brief.html
~/Desktop/Daily_Inspiration/shadowbroker_24h_brief.md
~/Desktop/Daily_Inspiration/pat_labs_threat_history.json   # rolling multi-day history
~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.html     # weekly meeting pack
~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.md
```

---

## Requirements

- MacBook Pro (Intel or Apple Silicon)
- **Docker Desktop** with ~8 GB+ RAM allocated if possible
- **Git**, **Python 3** (stdlib only for briefs)
- **Ollama** + disk for `olmo-3:32b-think` (~19 GB)
- Network for feeds (and first image/model pulls)

---

## 1. Docker Desktop

1. Install from [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Open Docker and wait until it is running
3. **Settings → Resources**: give Docker at least 8 GB RAM if the host has 16 GB+

---

## 2. Shadowbroker (your fork)

```bash
cd ~
git clone https://github.com/Bobpick/Shadowbroker.git
cd Shadowbroker

cp .env.example .env
# Edit .env as needed (ports, API keys, GT flags, etc.)
# Typical defaults:
#   FRONTEND_PORT=3000
#   BACKEND_PORT=3050

# Pull prebuilt images (fast):
docker compose pull
docker compose up -d

# OR build from YOUR local source (includes daily/weekly brief scripts + delta fixes):
# docker compose -f docker-compose.yml -f docker-compose.build.yml build
# docker compose -f docker-compose.yml -f docker-compose.build.yml up -d
```

Verify:

- Dashboard: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- API: [http://127.0.0.1:3050/api/health](http://127.0.0.1:3050/api/health)

Recovery scripts in the repo:

```bash
chmod +x quick_restart.sh nuke.sh
./quick_restart.sh    # bounce stack; free ports 3000/3050
# ./nuke.sh           # full reinstall from origin/main (prompts; preserves .env)
```

---

## 3. Ollama + `olmo-3:32b-think`

```bash
# Homebrew (recommended)
brew install ollama

# Start Ollama (app or service)
open -a Ollama 2>/dev/null || brew services start ollama || ollama serve &

ollama pull olmo-3:32b-think
ollama list
```

Check API:

```bash
curl -s http://127.0.0.1:11434/api/tags | head
```

---

## 4. Daily brief (PAT Labs Threat Assessment)

```bash
cd ~/Shadowbroker
chmod +x scripts/run_daily_24h_brief.sh scripts/daily_24h_brief.py scripts/run_weekly_intel_brief.sh scripts/weekly_intel_brief.py

mkdir -p ~/Desktop/Daily_Inspiration
```

### Manual test

Shadowbroker and Ollama must be up:

```bash
export SHADOWBROKER_URL=http://127.0.0.1:3050
export OLLAMA_URL=http://127.0.0.1:11434
export DAILY_BRIEF_OLLAMA_MODEL=olmo-3:32b-think
export DAILY_BRIEF_OUT_DIR="$HOME/Desktop/Daily_Inspiration"

# Prefer Homebrew/Xcode python3 if /usr/bin/python3 is missing:
python3 scripts/daily_24h_brief.py --no-email
```

If `run_daily_24h_brief.sh` fails on Python path, edit it so the last command uses `python3` instead of `/usr/bin/python3`, or install CLT:

```bash
xcode-select --install
```

### Schedule 6:30 AM local

**Option A — cron**

```bash
crontab -e
```

```cron
30 6 * * * /bin/bash /Users/YOURNAME/Shadowbroker/scripts/run_daily_24h_brief.sh
```

On modern macOS, grant **Full Disk Access** to Terminal (or `cron`) if Desktop writes are blocked:  
**System Settings → Privacy & Security → Full Disk Access**.

**Option B — launchd (preferred on Mac)**

Create `~/Library/LaunchAgents/com.patlabs.dailybrief.plist` (replace `YOURNAME`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.patlabs.dailybrief</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/YOURNAME/Shadowbroker/scripts/run_daily_24h_brief.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/YOURNAME/.shadowbroker/logs/daily_24h_brief.launchd.out</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOURNAME/.shadowbroker/logs/daily_24h_brief.launchd.err</string>
</dict>
</plist>
```

```bash
mkdir -p ~/.shadowbroker/logs
launchctl load ~/Library/LaunchAgents/com.patlabs.dailybrief.plist
```

**Mac reliability notes**

- Docker Desktop and Ollama should **open at login**
- If the Mac is **asleep at 6:30**, the job may run only after wake — leave plugged in / adjust Energy settings if the brief must fire on time

---

## 5. Weekly intel meeting pack

Builds a **past-7-day** executive summary for weekly intel meetings from the rolling history JSON (filled by daily runs) plus live feeds.

```bash
# After at least a few daily runs (best with 7 days of history):
python3 scripts/weekly_intel_brief.py --no-email

# Or:
./scripts/run_weekly_intel_brief.sh
```

Suggested schedule (e.g. **Monday 07:00** before the meeting):

```cron
0 7 * * 1 /bin/bash /Users/YOURNAME/Shadowbroker/scripts/run_weekly_intel_brief.sh
```

Or a second LaunchAgent with `Weekday = 1` (Sunday=1 in launchd… use cron if unsure), Hour 7, Minute 0.

Outputs:

- `~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.html`
- `~/Desktop/Daily_Inspiration/pat_labs_weekly_intel.md`

---

## 6. Email (optional)

Default: **write files only** — attach HTML yourself.

Auto-send: set SMTP env vars (`DAILY_BRIEF_SMTP_*` or `DELTA_REPORT_SMTP_*`) and `DAILY_BRIEF_EMAIL=true` (daily) / `WEEKLY_BRIEF_EMAIL=true` (weekly).

---

## 7. Brief-only Mac (Shadowbroker elsewhere)

If Shadowbroker runs on another host:

```bash
export SHADOWBROKER_URL=http://THAT-HOST:3050
```

Only Python + Ollama + scripts are required on the Mac. The remote API must be reachable (not bound only to localhost on the server without a tunnel/VPN).

---

## Checklist

1. Docker Desktop running  
2. `docker compose up -d` in the Shadowbroker clone  
3. `ollama pull olmo-3:32b-think` and Ollama running  
4. `python3 scripts/daily_24h_brief.py --no-email` once by hand  
5. Schedule daily 6:30 + weekly (e.g. Monday 07:00)  
6. Open HTML under `~/Desktop/Daily_Inspiration/`  

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Dashboard blank / port in use | `./quick_restart.sh` (kills host listeners on 3000/3050) |
| Frontend won’t bind 3000 | Quit other Next.js apps; free port; restart Docker |
| No Ollama prose | `ollama list`, `ollama serve`, model name `olmo-3:32b-think` |
| Empty 3-day / weekly history | Need successful daily runs; weekly is weak until ~7 days exist |
| Cron can’t write Desktop | Full Disk Access for the scheduler / Terminal |
| Python not found | `xcode-select --install` or Homebrew `python3` |

---

## Related scripts

| Path | Purpose |
|------|---------|
| `scripts/daily_24h_brief.py` | Daily PAT Labs brief |
| `scripts/run_daily_24h_brief.sh` | Daily wrapper + log |
| `scripts/weekly_intel_brief.py` | Weekly meeting pack |
| `scripts/run_weekly_intel_brief.sh` | Weekly wrapper + log |
| `quick_restart.sh` | Fast recovery |
| `nuke.sh` | Clean reinstall from git |

Log directory: `~/.shadowbroker/logs/`
