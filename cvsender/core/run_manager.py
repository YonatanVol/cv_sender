"""Owns the single active run and the one long-lived worker loop.

Previously each run got a brand-new event loop that was closed at the end —
which made it impossible to reuse a browser across runs (Playwright objects are
bound to their creating loop), so every run spawned fresh Chrome windows. Now a
single daemon thread runs one event loop forever and runs are submitted onto it,
letting `engine.session` keep one browser alive.
"""
from __future__ import annotations

import asyncio
import threading
import time

from .. import config
from ..db import store
from ..engine.session import session
from ..engine.worker import run_prepare, run_send
from .cancel import CancelToken, Cancelled


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._future: asyncio.Future | None = None
        self._cancel: CancelToken | None = None
        self._run_id: int | None = None

    # ---------------------------- loop ---------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()

            def _run():
                asyncio.set_event_loop(loop)
                loop.run_forever()

            t = threading.Thread(target=_run, daemon=True, name="cvsender-worker")
            t.start()
            self._loop, self._thread = loop, t
            return loop

    def busy(self) -> bool:
        with self._lock:
            return self._future is not None and not self._future.done()

    # ---------------------------- runs ---------------------------------
    def start_prepare(self, run_id: int, options: dict) -> bool:
        return self._start(run_id, lambda c: run_prepare(run_id, options, c))

    def start_send(self, run_id: int) -> bool:
        return self._start(run_id, lambda c: run_send(run_id, c))

    def start_takeover(self, item_id: int) -> bool:
        """Open one application pre-filled in a visible window for the human."""
        from ..engine.worker import run_takeover
        return self._start(-item_id, lambda c: run_takeover(item_id, c))

    def _start(self, run_id: int, factory) -> bool:
        loop = self._ensure_loop()
        with self._lock:
            if self._future is not None and not self._future.done():
                return False
            cancel = CancelToken()
            self._cancel, self._run_id = cancel, run_id
        fut = asyncio.run_coroutine_threadsafe(
            self._guarded(run_id, factory, cancel), loop)
        with self._lock:
            self._future = fut
        return True

    async def _guarded(self, run_id: int, factory, cancel: CancelToken) -> None:
        try:
            await factory(cancel)
        except Cancelled:
            store.update_run(run_id, status="cancelled", finished_at=time.time(),
                             message="Cancelled by user")
            store.add_event(run_id, "run.state", "cancelled",
                            data={"status": "cancelled"})
        except Exception as e:  # noqa: BLE001 — never crash silently
            store.update_run(run_id, status="error", finished_at=time.time(),
                             message=f"{type(e).__name__}: {e}"[:200])
            store.add_event(run_id, "run.error", str(e)[:200], level="error")
        finally:
            with self._lock:
                self._cancel = self._run_id = None

    def request_cancel(self, run_id: int) -> None:
        store.request_cancel(run_id)                 # durable first
        with self._lock:
            loop, cancel, active = self._loop, self._cancel, self._run_id
        if loop and cancel and active == run_id:
            loop.call_soon_threadsafe(cancel.set)    # wake the worker now

    # -------------------------- browser --------------------------------
    def close_browser(self) -> None:
        """Release the shared browser (idle cleanup / shutdown)."""
        with self._lock:
            loop = self._loop
        if loop:
            asyncio.run_coroutine_threadsafe(session.close(), loop).result(20)


manager = RunManager()
