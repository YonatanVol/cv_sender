"""One long-lived browser, reused across runs.

v1/v2 launched (and closed) an entire browser per phase, and LinkedIn ran
headful — so every run spawned Chrome windows. This session owns a single
Playwright instance plus two long-lived contexts:

  * ATS      — ephemeral context, headless, no login needed
  * LinkedIn — persistent context (the saved login), headless by default

Per item we open/close **pages**, not browsers. Everything here must run inside
the RunManager's single long-lived event loop: Playwright objects are bound to
the loop that created them.
"""
from __future__ import annotations

import asyncio
import time

from playwright.async_api import async_playwright

from ..config import LINKEDIN_PROFILE_DIR, USER_AGENT

VIEWPORT = {"width": 1280, "height": 900}


class BrowserSession:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None          # ATS (ephemeral)
        self._ats_ctx = None
        self._li_ctx = None           # LinkedIn (persistent)
        self._li_headless: bool | None = None
        self._lock = asyncio.Lock()
        self.last_used = 0.0

    # ------------------------------------------------------------------
    async def _ensure_pw(self):
        if self._pw is None:
            self._pw = await async_playwright().start()
        return self._pw

    @staticmethod
    def _alive(obj) -> bool:
        """A context/browser can die (crash, user closed the window)."""
        if obj is None:
            return False
        try:
            browser = getattr(obj, "browser", None)
            if browser is not None:
                return browser.is_connected()
            return obj.is_connected()
        except Exception:
            return False

    async def ats_context(self, headless: bool = True):
        """Shared ephemeral context for ATS forms (no login)."""
        async with self._lock:
            self.last_used = time.time()
            if not self._alive(self._ats_ctx):
                pw = await self._ensure_pw()
                self._browser = await pw.chromium.launch(headless=headless)
                self._ats_ctx = await self._browser.new_context(
                    user_agent=USER_AGENT, viewport=VIEWPORT)
            return self._ats_ctx

    async def linkedin_context(self, headless: bool = True):
        """Persistent context holding the saved LinkedIn login.

        Headless by default — the session works fine headless once logged in,
        which is what stops windows appearing on every run. Assist mode asks for
        headless=False; if the visibility differs from the live context we
        recycle it so the user actually gets a window.
        """
        async with self._lock:
            self.last_used = time.time()
            if self._alive(self._li_ctx) and self._li_headless != headless:
                try:
                    await self._li_ctx.close()
                except Exception:
                    pass
                self._li_ctx = None
            if not self._alive(self._li_ctx):
                pw = await self._ensure_pw()
                LINKEDIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                self._li_ctx = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(LINKEDIN_PROFILE_DIR),
                    headless=headless, user_agent=USER_AGENT,
                    viewport=VIEWPORT,
                    args=["--disable-blink-features=AutomationControlled"])
                self._li_headless = headless
            return self._li_ctx

    # ------------------------------------------------------------------
    async def close(self) -> None:
        async with self._lock:
            for obj in (self._li_ctx, self._ats_ctx, self._browser):
                try:
                    if obj is not None:
                        await obj.close()
                except Exception:
                    pass
            self._li_ctx = self._ats_ctx = self._browser = None
            self._li_headless = None
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None

    async def close_if_idle(self, idle_s: float) -> bool:
        if self.last_used and (time.time() - self.last_used) > idle_s:
            await self.close()
            return True
        return False


# One session per process, living in the RunManager's loop.
session = BrowserSession()
