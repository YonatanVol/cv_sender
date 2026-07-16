"""Open a real Chrome window for a one-time LinkedIn login.

You log in (and pass any 2FA) yourself in the window that appears. The session
is saved to data/linkedin_profile/ so future automated runs stay logged in.
We never see or store your password.

Run:  python scripts/linkedin_login.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402


def logged_in(page) -> bool:
    url = (page.url or "").lower()
    if "/feed" in url:
        return True
    try:
        if page.query_selector("#global-nav"):
            return True
    except Exception:
        pass
    return False


def _navigate(page) -> bool:
    """Load the LinkedIn login page, retrying a few times. Returns True on load."""
    for attempt in range(3):
        try:
            page.goto("https://www.linkedin.com/login",
                      wait_until="domcontentloaded", timeout=45000)
            try:
                page.bring_to_front()
            except Exception:
                pass
            url = (page.url or "").lower()
            if "linkedin.com" in url:
                print(f"LOADED {page.url}", flush=True)
                return True
            print(f"NAV_ATTEMPT {attempt+1}: landed on {page.url}", flush=True)
        except Exception as e:
            print(f"NAV_ATTEMPT {attempt+1} error: {e}"[:140], flush=True)
        time.sleep(3)
    return False


def main(max_wait_seconds: int = 360) -> int:
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        loaded = _navigate(page)
        if not loaded:
            print("NAV_FAILED — could not reach linkedin.com from this browser.",
                  flush=True)

        if logged_in(page):
            print("ALREADY_LOGGED_IN", flush=True)
            time.sleep(1)
            ctx.close()
            return 0

        print("WINDOW_OPEN — log in to LinkedIn in the Chrome window…", flush=True)
        deadline = max_wait_seconds // 5
        ok = False
        for _ in range(deadline):
            time.sleep(5)
            try:
                if logged_in(page):
                    ok = True
                    break
            except Exception:
                continue
        # Give LinkedIn a moment to settle, then close to flush the session.
        time.sleep(2)
        ctx.close()
        print("LOGGED_IN" if ok else "NOT_LOGGED_IN", flush=True)
        return 0 if ok else 1


if __name__ == "__main__":
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 360
    raise SystemExit(main(wait))
