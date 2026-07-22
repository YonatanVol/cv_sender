"""Central paths and tunables for CV Sender v2."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # repo root
DATA_DIR = ROOT / "data2"                              # v2 data (kept apart from v1's data/)
DB_PATH = DATA_DIR / "cvsender.db"
SCREENSHOT_DIR = DATA_DIR / "shots"
CV_DIR = DATA_DIR / "cv"
LINKEDIN_PROFILE_DIR = DATA_DIR / "linkedin_profile"   # persistent browser login
BOARDS_PATH = DATA_DIR / "boards.yaml"

# Bind the local server to loopback only — the confirm endpoints trigger real,
# irreversible outward actions, so the surface must never be network-reachable.
HOST = "127.0.0.1"
PORT = 8010

# Engine timing / safety.
STEP_TIMEOUT_S = 45.0        # hard ceiling on any single Playwright step
PREPARE_DELAY_S = 2.0        # polite pause between prepared items
SEND_DELAY_S = 6.0           # human-scale pause between real sends (ban safety)
SEND_JITTER_S = 3.0          # added random 0..jitter to each send delay
MAX_ATTEMPTS = 4             # per-item retry cap before a job stops being re-offered
HEARTBEAT_S = 2.0            # run heartbeat cadence (crash detection)
STALE_RUN_S = 30.0           # a run with an older heartbeat is considered dead

# A normal-looking desktop UA reduces trivial automation flags.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

for _d in (DATA_DIR, SCREENSHOT_DIR, CV_DIR):
    _d.mkdir(parents=True, exist_ok=True)
