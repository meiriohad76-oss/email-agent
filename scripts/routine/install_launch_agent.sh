#!/bin/bash
# Installs the app server and the scheduled routine as per-user launchd agents.
# The server starts at login and restarts if it exits. The routine runs at
# 14:30 and 02:00 local time (the Mac is set to Asia/Jerusalem).
# Usage: scripts/routine/install_launch_agent.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
    echo "Missing $PROJECT_DIR/.venv/bin/python. Create the virtualenv first." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/email-article-analyzer" "$PROJECT_DIR/data"

for LABEL in com.email-article-analyzer.server com.email-article-analyzer.routine; do
    TEMPLATE="$PROJECT_DIR/scripts/routine/$LABEL.plist.template"
    TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
    sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$TARGET"
    plutil -lint "$TARGET"
    # Reload if already loaded so schedule or path edits take effect.
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$TARGET"
    echo "Installed $LABEL"
done

echo "Check status with: launchctl print gui/$(id -u)/com.email-article-analyzer.server"
