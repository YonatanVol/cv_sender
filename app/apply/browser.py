"""Playwright browser lifecycle helpers (sync API, run inside a worker thread).

Two flavors:
  - launch_browser():    ephemeral context for ATS forms (no login needed).
  - launch_persistent():  persistent profile for LinkedIn so the one-time
                          manual login survives across runs (we never store
                          the password ourselves).
"""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LINKEDIN_PROFILE_DIR = DATA_DIR / "linkedin_profile"

# A normal-looking desktop UA reduces trivial automation flags.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def launch_browser(p, headless: bool = False):
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
    return browser, context


def launch_persistent(p, headless: bool = False, user_data_dir=None):
    # Account isolation: each person can pass their own profile dir so logins
    # never mix. Defaults to Yonatan's dir for backward compatibility.
    profile_dir = Path(user_data_dir) if user_data_dir else LINKEDIN_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
