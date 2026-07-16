"""One-time LinkedIn login for ANY person, into an isolated profile dir.

Usage:  python scripts/li_login.py <person_slug> [wait_seconds]
Example: python scripts/li_login.py shani 900

Opens a real Chrome window pointed at LinkedIn login using
data/li_profiles/<person_slug>/ as the browser profile. The person logs in
themselves (incl. 2FA); the session persists there. We never store the password,
and each person's login is fully separate from everyone else's.
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
    for attempt in range(3):
        try:
            page.goto("https://www.linkedin.com/login",
                      wait_until="domcontentloaded", timeout=45000)
            try:
                page.bring_to_front()
            except Exception:
                pass
            if "linkedin.com" in (page.url or "").lower():
                print(f"LOADED {page.url}", flush=True)
                return True
        except Exception as e:
            print(f"NAV_ATTEMPT {attempt+1} error: {e}"[:140], flush=True)
        time.sleep(3)
    return False


def main(slug: str, max_wait_seconds: int) -> int:
    profile_dir = ROOT / "data" / "li_profiles" / slug
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _navigate(page)
        if logged_in(page):
            print("ALREADY_LOGGED_IN", flush=True)
            time.sleep(1)
            ctx.close()
            return 0
        print(f"WINDOW_OPEN — log in to {slug}'s LinkedIn in the Chrome window…", flush=True)
        ok = False
        for _ in range(max_wait_seconds // 5):
            time.sleep(5)
            try:
                if logged_in(page):
                    ok = True
                    break
            except Exception:
                continue
        time.sleep(2)
        ctx.close()
        print("LOGGED_IN" if ok else "NOT_LOGGED_IN", flush=True)
        return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: li_login.py <person_slug> [wait_seconds]")
        raise SystemExit(2)
    slug = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    raise SystemExit(main(slug, wait))
