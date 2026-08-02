#!/usr/bin/env bash
# Weekly PAT Labs intel pack (past 7 days) → Desktop/Daily_Inspiration fixed filenames.
# Suggested: 0 7 * * 1  (Monday 07:00 local, before weekly meeting)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${HOME}/.shadowbroker/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/weekly_intel_brief.log"

{
  echo "==== $(date -Is) start ===="
  if [[ -x "${HOME}/bin/enable_internet.sh" ]]; then
    "${HOME}/bin/enable_internet.sh" || true
  fi

  export SHADOWBROKER_URL="${SHADOWBROKER_URL:-http://127.0.0.1:3050}"
  export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  export DAILY_BRIEF_OLLAMA_MODEL="${DAILY_BRIEF_OLLAMA_MODEL:-cogito:32b}"
  export WEEKLY_BRIEF_OLLAMA_MODEL="${WEEKLY_BRIEF_OLLAMA_MODEL:-${DAILY_BRIEF_OLLAMA_MODEL}}"
  export DAILY_BRIEF_OUT_DIR="${DAILY_BRIEF_OUT_DIR:-${HOME}/Desktop/Daily_Inspiration}"

  PY=python3
  if [[ -x /usr/bin/python3 ]]; then
    PY=/usr/bin/python3
  fi
  "$PY" "$ROOT/scripts/weekly_intel_brief.py" "$@"
  echo "==== $(date -Is) done exit=$? ===="
} >>"$LOG" 2>&1
