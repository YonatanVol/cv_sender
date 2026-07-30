"""Cooperative cancellation. The worker checks the token between items and
inside every wait; a Playwright step is wrapped so a hung page cannot wedge a
cancel."""
from __future__ import annotations

import asyncio


class Cancelled(Exception):
    """Raised when a run's cancel token has been set."""


class CancelToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    async def sleep(self, delay: float) -> None:
        """Sleep, but wake immediately (and raise) if cancelled."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return                 # slept the full delay, not cancelled
        raise Cancelled()

    async def guard(self, coro, timeout: float):
        """Run a coroutine with a hard timeout AND cancel responsiveness."""
        waiter = asyncio.ensure_future(self._event.wait())
        task = asyncio.ensure_future(coro)
        done, pending = await asyncio.wait(
            {waiter, task}, timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            waiter.cancel()
            return task.result()
        # cancelled or timed out -> tear down the step
        task.cancel()
        waiter.cancel()
        if self._event.is_set():
            raise Cancelled()
        raise asyncio.TimeoutError(f"step exceeded {timeout}s")
