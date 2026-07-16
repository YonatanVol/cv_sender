"""Read the logged-in profile for ANY person (isolated profile dir).

Usage:  python scripts/li_read.py <person_slug> <out_path>

Navigates to /in/me/ (the logged-in user's own profile), scrolls to load all
sections, and dumps the visible text. Read-only.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402


def main(slug: str, out_path: str) -> int:
    profile_dir = ROOT / "data" / "li_profiles" / slug
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=True, user_data_dir=profile_dir)
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
        for _ in range(10):
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
        Path(out_path).write_text(f"PROFILE_URL: {page.url}\n\n{text}", encoding="utf-8")
        print(f"OK saved {len(text)} chars; url={page.url}", flush=True)
        ctx.close()
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: li_read.py <person_slug> <out_path>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
