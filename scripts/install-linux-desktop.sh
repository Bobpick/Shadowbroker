#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$SCRIPT_DIR/linux-desktop-launch.sh"
ICON="$REPO_ROOT/desktop-shell/tauri-skeleton/src-tauri/icons/128x128.png"
APP_ID="shadowbroker.desktop"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"

chmod +x "$LAUNCHER"

mkdir -p "$APPS_DIR"

write_desktop_file() {
  local target="$1"
  cat >"$target" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ShadowBroker
GenericName=Geospatial Intelligence Dashboard
Comment=Global Threat Intercept — real-time OSINT map dashboard
Exec=${LAUNCHER}
Icon=${ICON}
Path=${REPO_ROOT}
Terminal=false
StartupNotify=true
Categories=Network;Science;Utility;
Keywords=osint;intelligence;map;geospatial;shadowbroker;
EOF
}

write_desktop_file "$APPS_DIR/$APP_ID"

if [[ -d "$DESKTOP_DIR" ]]; then
  write_desktop_file "$DESKTOP_DIR/ShadowBroker.desktop"
  chmod +x "$DESKTOP_DIR/ShadowBroker.desktop" 2>/dev/null || true
  if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/ShadowBroker.desktop" metadata::trusted true 2>/dev/null || true
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed ShadowBroker desktop launcher:"
echo "  Application menu: $APPS_DIR/$APP_ID"
if [[ -d "$DESKTOP_DIR" ]]; then
  echo "  Desktop shortcut: $DESKTOP_DIR/ShadowBroker.desktop"
fi
FRONTEND_PORT=3000
if [[ -f "$REPO_ROOT/.env" ]]; then
  port_from_env="$(grep -E '^[[:space:]]*FRONTEND_PORT=' "$REPO_ROOT/.env" | tail -n 1 | cut -d= -f2- | tr -d '[:space:]"'"'"'')"
  if [[ -n "$port_from_env" ]]; then
    FRONTEND_PORT="$port_from_env"
  fi
fi
echo "Dashboard URL: http://127.0.0.1:${FRONTEND_PORT}"