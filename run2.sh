#!/usr/bin/env bash
# Launch CV Sender v2 (loopback only) and open it in the browser.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv; ./.venv/bin/python -m pip install -q -r requirements.txt; ./.venv/bin/python -m playwright install chromium; }
URL="http://127.0.0.1:8010"
( sleep 2; command -v open >/dev/null && open "$URL" ) &
exec ./.venv/bin/python -m uvicorn cvsender.main:app --host 127.0.0.1 --port 8010
