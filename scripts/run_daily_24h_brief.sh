#!/usr/bin/env bash
# Morning 24h family brief → Desktop/Daily_Inspiration (fixed filenames).
# Schedule: 30 6 * * *  (6:30 AM local)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${HOME}/.shadowbroker/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_24h_brief.log"

{
  echo "==== $(date -Is) start ===="
  # Optional: re-enable if your host gates internet for morning jobs
  if [[ -x "${HOME}/bin/enable_internet.sh" ]]; then
    "${HOME}/bin/enable_internet.sh" || true
  fi

  export SHADOWBROKER_URL="${SHADOWBROKER_URL:-http://127.0.0.1:3050}"
  export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  export DAILY_BRIEF_OLLAMA_MODEL="${DAILY_BRIEF_OLLAMA_MODEL:-olmo-3:32b-think}"
  export DAILY_BRIEF_OUT_DIR="${DAILY_BRIEF_OUT_DIR:-${HOME}/Desktop/Daily_Inspiration}"

  # Set DAILY_BRIEF_EMAIL=true (and SMTP vars) if you want auto-send.
  # Default: write MD+HTML only — attach HTML when you email friends/family yourself.
  PY=python3
  if [[ -x /usr/bin/python3 ]]; then
    PY=/usr/bin/python3
  fi
  "$PY" "$ROOT/scripts/daily_24h_brief.py" "$@"
  echo "==== $(date -Is) done exit=$? ===="
} >>"$LOG" 2>&1
