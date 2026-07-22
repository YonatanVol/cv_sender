"""In-process pub/sub so the SSE endpoint flushes immediately when the worker
appends an event, with a DB-cursor fallback. Events themselves are durable in
run_events; this is only the wake-up signal."""
from __future__ import annotations

import asyncio
from collections import defaultdict


class Broker:
    def __init__(self) -> None:
        self._conds: dict[int, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def notify(self, run_id: int) -> None:
        cond = self._conds[run_id]
        async with cond:
            cond.notify_all()

    async def wait(self, run_id: int, timeout: float) -> None:
        cond = self._conds[run_id]
        async with cond:
            try:
                await asyncio.wait_for(cond.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return


broker = Broker()
