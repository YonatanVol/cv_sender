#!/usr/bin/env bash
# Keep CV Sender running: start at login, restart if it dies, survive a reboot.
#
#   bash scripts/install_launchd.sh            # install + start
#   bash scripts/install_launchd.sh --remote   # also reachable from your phone
#   bash scripts/install_launchd.sh --uninstall
#
# It runs the server, which owns the browser and the scheduler. The scheduler
# only stages applications; sending always waits for your confirm.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.cvsender.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$REPO/.venv/bin/python"
PORT="${CVS_PORT:-8010}"
HOST="127.0.0.1"
[ "${1:-}" = "--remote" ] && HOST="0.0.0.0"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

[ -x "$PY" ] || { echo "No virtualenv at $PY — run ./run2.sh once first."; exit 1; }
if [ "$HOST" != "127.0.0.1" ]; then
  "$PY" - <<'EOF' || { echo "Set a passphrase first: $PY -m cvsender.setpass"; exit 1; }
import sys
from cvsender import auth
from cvsender.db.migrations import migrate
migrate()
sys.exit(0 if auth.is_configured() else 1)
EOF
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data2/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>$PY</string><string>-m</string><string>uvicorn</string>
    <string>cvsender.main:app</string>
    <string>--host</string><string>$HOST</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CVS_HOST</key><string>$HOST</string>
    <key>CVS_PORT</key><string>$PORT</string>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$REPO/data2/logs/server.log</string>
  <key>StandardErrorPath</key><string>$REPO/data2/logs/server.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 2
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "CV Sender is running and will restart itself (including after a reboot)."
  echo "  http://127.0.0.1:$PORT"
  [ "$HOST" = "0.0.0.0" ] && echo "  phone: http://$(ipconfig getifaddr en0 2>/dev/null || echo '<mac-ip>'):$PORT/assist"
else
  echo "Installed, but the server did not answer yet. Check data2/logs/server.log"
fi
echo
echo "Note: a launchd agent runs while you are logged in. Keep the Mac awake"
echo "(Settings > Lock Screen) if you want the morning run to happen."
