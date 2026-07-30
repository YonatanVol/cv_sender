"""Async Playwright lifecycle. Ephemeral context for ATS forms; a persistent
context for LinkedIn (login survives, we never store the password)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from playwright.async_api import async_playwright

from ..config import LINKEDIN_PROFILE_DIR, USER_AGENT


@asynccontextmanager
async def browser_context(headless: bool = True):
    """Ephemeral context — no login needed (ATS)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
        try:
            yield ctx
        finally:
            await ctx.close()
            await browser.close()


@asynccontextmanager
async def persistent_context(headless: bool = False):
    """Persistent profile for LinkedIn (session persists across runs)."""
    LINKEDIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(LINKEDIN_PROFILE_DIR),
            headless=headless, user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            await ctx.close()
