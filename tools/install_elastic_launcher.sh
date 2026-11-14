#!/usr/bin/env bash
# Creates a double-clickable desktop launcher for the elastic campaign dashboard.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
F="$DESK/Elastic Wing Campaign.desktop"
cat > "$F" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Elastic Wing Campaign
Comment=Plan, run and monitor the elastic wing study
Exec=bash "$ROOT/Run Elastic Campaign.sh"
Terminal=true
Icon=utilities-system-monitor
DESKTOP
chmod +x "$F"
gio set "$F" metadata::trusted true 2>/dev/null || true
echo "Launcher created: $F"
