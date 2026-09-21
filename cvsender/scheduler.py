"""The heartbeat that keeps the queue stocked without anyone starting it.

One daemon thread inside the server process, ticking once a minute:

* stages a batch every morning (and catches up if the Mac was asleep at 08:30),
* records a heartbeat so the app can tell "nothing happened" from "nobody ran",
* purges expired sessions.

It runs *inside the server* on purpose. The old setup was a second process
(``python -m cvsender.runner``) with its own browser: two processes fought over
the same LinkedIn profile directory, and either one could cancel the other's
run. Here, browser work is only ever submitted to the single RunManager, and
only while it is idle.

It never sends. Staging fills forms and parks them; every send stays behind a
human confirm.
"""
from __future__ import annotations

import threading
import time

from . import config, freshness
from .core.run_manager import manager
from .db import store

TICK_S = 60.0
DEFAULT_HOUR = 8
DEFAULT_MINUTE = 30
CATCHUP_UNTIL_HOUR = 20        # a missed morning is still worth staging at noon
ATS = ["greenhouse", "lever", "ashby", "comeet"]

# app_settings keys
LAST_TICK = "scheduler.last_tick"
LAST_STAGING = "scheduler.last_staging"
LAST_STAGING_RESULT = "scheduler.last_staging_result"
ENABLED = "scheduler.enabled"
LAST_VERIFY = "scheduler.last_verify"
VERIFY_PER_TICK = 10


def enabled() -> bool:
    return (store.get_setting(ENABLED) or "1") not in ("0", "false", "off")


def _int_setting(key: str, default: int) -> int:
    try:
        return int(store.get_setting(key) or default)
    except (TypeError, ValueError):
        return default


def target_depth() -> int:
    return max(0, _int_setting("run.target", 200))


def channels() -> list[str]:
    raw = store.get_setting("run.channels")
    picked = [c.strip() for c in (raw or "").split(",") if c.strip()]
    return picked or ATS


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def due_now(now: time.struct_time, last_staging_day: str | None) -> bool:
    """True when today's staging still has to happen, and it is time."""
    if last_staging_day == time.strftime("%Y-%m-%d", now):
        return False
    hour, minute = _int_setting("run.hour", DEFAULT_HOUR), _int_setting("run.minute", DEFAULT_MINUTE)
    after_start = (now.tm_hour, now.tm_min) >= (hour, minute)
    return after_start and now.tm_hour < CATCHUP_UNTIL_HOUR


def stage_now(cap: int | None = None) -> int | None:
    """Submit one staging run to the manager. Returns the run id, or None."""
    if manager.busy() or store.get_active_run():
        return None
    depth = len(store.assist_queue(limit=1000))
    need = target_depth() - depth
    if need <= 0:
        store.set_setting(LAST_STAGING_RESULT, f"queue already at {depth}")
        store.set_setting(LAST_STAGING, _today())
        return None
    options = {"channels": channels(), "mode": "dry",
               "cap": max(1, min(cap or need, config.MAX_CAP)),
               "geography": store.get_setting("run.geography") or "israel_remote",
               "strictness": store.get_setting("run.strictness") or "balanced",
               "concurrency": config.PREPARE_CONCURRENCY}
    run_id = store.create_run_atomic(options, "dry")
    if run_id is None:
        return None
    if not manager.start_prepare(run_id, options):
        store.update_run(run_id, status="error", message="manager busy")
        return None
    store.set_setting(LAST_STAGING, _today())
    store.set_setting(LAST_STAGING_RESULT, f"run #{run_id} staging up to {options['cap']}")
    return run_id


def tick() -> dict:
    """One scheduler beat. Pure enough to call from a test."""
    out = {"staged": None, "purged": 0, "verified": {}}
    store.set_setting(LAST_TICK, str(time.time()))
    out["purged"] = store.purge_expired_sessions()
    if not enabled():
        return out
    # Drain the unverified backlog a few postings at a time, so a dead job
    # never sits at the top of the queue and no board is hammered.
    if not manager.busy():
        out["verified"] = freshness.sweep(limit=VERIFY_PER_TICK)
        if out["verified"].get("closed"):
            store.set_setting(LAST_VERIFY,
                              f"{out['verified']['closed']} closed at {time.strftime('%H:%M')}")
    if due_now(time.localtime(), store.get_setting(LAST_STAGING)):
        out["staged"] = stage_now()
    return out


def _loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            tick()
        except Exception as e:                      # never kill the thread
            try:
                store.set_setting(LAST_STAGING_RESULT, f"tick error: {type(e).__name__}: {e}"[:200])
            except Exception:
                pass
        stop.wait(TICK_S)


_stop = threading.Event()
_thread: threading.Thread | None = None


def start() -> None:
    """Start the scheduler thread once per process."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(_stop,), daemon=True,
                               name="cvs-scheduler")
    _thread.start()


def stop() -> None:
    _stop.set()


def status() -> dict:
    last_tick = store.get_setting(LAST_TICK)
    try:
        age = time.time() - float(last_tick) if last_tick else None
    except (TypeError, ValueError):
        age = None
    return {
        "enabled": enabled(),
        "running": bool(_thread and _thread.is_alive()),
        "last_tick_age_s": round(age) if age is not None else None,
        "last_staging_day": store.get_setting(LAST_STAGING),
        "last_staging_result": store.get_setting(LAST_STAGING_RESULT),
        "next_staging_at": f"{_int_setting('run.hour', DEFAULT_HOUR):02d}:"
                           f"{_int_setting('run.minute', DEFAULT_MINUTE):02d}",
        "last_verify": store.get_setting(LAST_VERIFY),
        "target_depth": target_depth(),
        "channels": channels(),
    }
