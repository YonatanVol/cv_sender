"""Read the logged-in user's own LinkedIn profile and dump it to a file.

Read-only: navigates to /in/me/, scrolls to load the sections, and saves the
visible text so we can analyze and improve it. No edits are made.

Run:  python scripts/linkedin_profile_read.py [out_path]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402


def main(out_path: str) -> int:
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.linkedin.com/in/me/",
                      wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"NAV_ERROR {e}"[:140], flush=True)
        page.wait_for_timeout(4000)
        url = page.url
        if "/login" in url.lower() or "/authwall" in url.lower():
            print("NOT_LOGGED_IN", flush=True)
            ctx.close()
            return 1

        # Scroll to force lazy sections (About / Experience / Education) to load.
        for _ in range(8):
            try:
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(700)
            except Exception:
                break
        try:
            page.goto("https://www.linkedin.com/in/me/", timeout=30000)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        try:
            text = page.inner_text("main")
        except Exception:
            text = page.inner_text("body")
        try:
            name = page.inner_text("h1")
        except Exception:
            name = ""

        Path(out_path).write_text(
            f"PROFILE_URL: {page.url}\nNAME: {name}\n\n{text}", encoding="utf-8")
        print(f"OK saved {len(text)} chars to {out_path}", flush=True)
        print(f"PROFILE_URL {page.url}", flush=True)
        print(f"NAME {name}", flush=True)
        ctx.close()
        return 0


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/li_profile.txt"
    raise SystemExit(main(out))
