#!/usr/bin/env bash
# Launch CV Sender v2.
#
#   ./run2.sh              local only (127.0.0.1) — the safe default
#   ./run2.sh --remote     reachable from your phone (requires a passphrase)
set -e
cd "$(dirname "$0")"

PY=./.venv/bin/python
[ -d .venv ] || { python3 -m venv .venv; $PY -m pip install -q -r requirements.txt; $PY -m playwright install chromium; }

PORT=8010
HOST=127.0.0.1
REMOTE=0
[ "$1" = "--remote" ] && REMOTE=1

if [ "$REMOTE" = "1" ]; then
  # These endpoints fire REAL job applications, so remote access requires auth.
  if ! $PY -c "
from cvsender.db.migrations import migrate; migrate()
from cvsender import auth
raise SystemExit(0 if auth.is_configured() else 1)" 2>/dev/null; then
    echo "✗ No passphrase set — refusing to expose the app."
    echo "  Set one first:  $PY -m cvsender.setpass"
    exit 1
  fi
  HOST=0.0.0.0
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
  URL="http://${LAN_IP:-<this-machine>}:$PORT/assist"
  echo "🔓 Remote access ON (passphrase required at sign-in)"
  echo "   On the same Wi-Fi:  $URL"
  echo
  if command -v qrencode >/dev/null; then
    qrencode -t ANSIUTF8 "$URL"
  else
    echo "   (brew install qrencode to print a scannable QR here)"
  fi
  echo
  echo "   From anywhere (recommended — no public URL, device-level auth):"
  echo "     brew install --cask tailscale   # then enable it on Mac + phone"
  echo "     open http://<your-mac>.<tailnet>.ts.net:$PORT/assist"
  echo
  echo "   Tip: add the page to your home screen to install it as an app."
else
  ( sleep 2; command -v open >/dev/null && open "http://127.0.0.1:$PORT" ) &
fi

# CVS_HOST is what the app's own startup guard checks, so the bind address and
# the safety check can never disagree.
export CVS_HOST="$HOST" CVS_PORT="$PORT"
exec $PY -m uvicorn cvsender.main:app --host "$HOST" --port "$PORT"
