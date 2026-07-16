#!/usr/bin/env bash
# Launch the CV Sender local web app, then open it in your browser.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -q -r requirements.txt
  ./.venv/bin/python -m playwright install chromium
fi

URL="http://127.0.0.1:8000"
( sleep 2; command -v open >/dev/null && open "$URL" ) &
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
