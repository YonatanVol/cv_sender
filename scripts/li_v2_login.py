"""One-time LinkedIn login for the CV Sender v2 persistent profile.

Opens a real Chrome window; you log in yourself (incl. 2FA). The session is
saved to data2/linkedin_profile/ so v2 runs stay logged in. Password never
stored or read by us.

Run:  python scripts/li_v2_login.py [max_wait_seconds]
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cvsender.engine.browser import persistent_context  # noqa: E402


async def _logged_in(page) -> bool:
    url = (page.url or "").lower()
    if "/feed" in url:
        return True
    try:
        return bool(await page.query_selector("#global-nav"))
    except Exception:
        return False


async def main(max_wait: int) -> int:
    async with persistent_context(headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto("https://www.linkedin.com/login",
                            wait_until="domcontentloaded", timeout=60000)
            await page.bring_to_front()
        except Exception:
            pass
        if await _logged_in(page):
            print("ALREADY_LOGGED_IN", flush=True)
            return 0
        print("WINDOW_OPEN — log in to LinkedIn in the Chrome window…", flush=True)
        for _ in range(max_wait // 5):
            await asyncio.sleep(5)
            if await _logged_in(page):
                await asyncio.sleep(2)
                print("LOGGED_IN", flush=True)
                return 0
        print("NOT_LOGGED_IN", flush=True)
        return 1


if __name__ == "__main__":
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    raise SystemExit(asyncio.run(main(wait)))
