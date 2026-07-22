"""Owns the single active run's worker thread + cancel token. One worker at a
time (single-user local tool); cancel is durable-first (DB flag) then in-memory."""
from __future__ import annotations

import asyncio
import threading
import time

from ..db import store
from ..engine.worker import run_prepare, run_send
from .cancel import CancelToken, Cancelled


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel: CancelToken | None = None
        self._run_id: int | None = None

    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start_prepare(self, run_id: int, options: dict) -> bool:
        return self._start(run_id, lambda c: run_prepare(run_id, options, c))

    def start_send(self, run_id: int) -> bool:
        return self._start(run_id, lambda c: run_send(run_id, c))

    def _start(self, run_id: int, factory) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            t = threading.Thread(target=self._worker, args=(run_id, factory),
                                 daemon=True)
            self._thread = t
        t.start()
        return True

    def _worker(self, run_id: int, factory) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cancel = CancelToken()
        with self._lock:
            self._loop, self._cancel, self._run_id = loop, cancel, run_id
        try:
            loop.run_until_complete(factory(cancel))
        except Cancelled:
            store.update_run(run_id, status="cancelled", finished_at=time.time(),
                             message="Cancelled by user")
            store.add_event(run_id, "run.state", "cancelled",
                            data={"status": "cancelled"})
        except Exception as e:  # noqa: BLE001 — worker must never crash silently
            store.update_run(run_id, status="error", finished_at=time.time(),
                             message=f"{type(e).__name__}: {e}"[:200])
            store.add_event(run_id, "run.error", str(e)[:200], level="error")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            with self._lock:
                self._loop = self._cancel = self._run_id = None
                self._thread = None

    def request_cancel(self, run_id: int) -> None:
        store.request_cancel(run_id)                 # durable first
        with self._lock:
            loop, cancel, active = self._loop, self._cancel, self._run_id
        if loop and cancel and active == run_id:
            loop.call_soon_threadsafe(cancel.set)    # wake the worker now


manager = RunManager()
