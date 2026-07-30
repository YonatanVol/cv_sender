"""BrowserSession: one browser reused across runs (no window-per-run spam)."""
import asyncio

import pytest

from cvsender.engine.session import BrowserSession


def test_contexts_are_reused_across_calls():
    """Two prepare phases must share one context, not launch two browsers."""
    async def go():
        s = BrowserSession()
        try:
            a = await s.ats_context(headless=True)
            b = await s.ats_context(headless=True)
            assert a is b, "ATS context should be reused, not relaunched"
            page = await a.new_page()          # per item we open PAGES...
            await page.close()                 # ...and closing one keeps the ctx
            c = await s.ats_context(headless=True)
            assert c is a and c.browser.is_connected()
        finally:
            await s.close()
    asyncio.run(go())


def test_close_is_idempotent_and_reopens():
    async def go():
        s = BrowserSession()
        a = await s.ats_context(headless=True)
        await s.close()
        await s.close()                        # second close must not raise
        b = await s.ats_context(headless=True)  # reopens on demand
        assert b is not a
        await s.close()
    asyncio.run(go())


def test_dead_context_is_detected_and_replaced():
    """If the browser dies (crash / user closed it) we relaunch instead of
    handing back a dead handle."""
    async def go():
        s = BrowserSession()
        try:
            a = await s.ats_context(headless=True)
            await a.browser.close()            # simulate a crash
            b = await s.ats_context(headless=True)
            assert b is not a and b.browser.is_connected()
        finally:
            await s.close()
    asyncio.run(go())
