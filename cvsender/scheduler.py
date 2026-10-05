"""The heartbeat that keeps the queue stocked without anyone starting it.

One daemon thread inside the server process, ticking once a minute:

* scans for new postings every hour during the day (2026-10-05: it used to scan
  once a morning, and only the job boards — never LinkedIn, the one channel
  where applications actually finish, so nothing was sent for 13 days),
* records a heartbeat so the app can tell "nothing happened" from "nobody ran",
* purges expired sessions.

It runs *inside the server* on purpose. The old setup was a second process
(``python -m cvsender.runner``) with its own browser: two processes fought over
the same LinkedIn profile directory, and either one could cancel the other's
run. Here, browser work is only ever submitted to the single RunManager, and
only while it is idle.

It never sends. A scan fills forms and parks them; sending is Yonatan's button
on the dashboard, every time.
"""
from __future__ import annotations

import threading
import time

from . import config, freshness
from .core.run_manager import manager
from .db import store

TICK_S = 60.0
DEFAULT_EVERY_MIN = 60
# No scans overnight: sending is manual, so a posting found at 03:00 waits for
# the morning anyway — and every scan is LinkedIn traffic on his account.
DEFAULT_FROM_HOUR = 7
DEFAULT_TO_HOUR = 23
DEFAULT_SCAN_CAP = 30
ATS = ["greenhouse", "lever", "ashby", "comeet"]
# LinkedIn first: it is where all 45 applications to date actually finished.
# The job boards gate almost every application behind a CAPTCHA or an emailed
# code, so leaving LinkedIn out — the old default — meant scanning only the
# channels that cannot send.
DEFAULT_CHANNELS = ["linkedin"] + ATS

# app_settings keys
LAST_TICK = "scheduler.last_tick"
LAST_STAGING = "scheduler.last_staging"
LAST_SCAN_AT = "scan.last_at"
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
    return picked or DEFAULT_CHANNELS


def every_min() -> int:
    return max(10, _int_setting("scan.every_min", DEFAULT_EVERY_MIN))


def window() -> tuple[int, int]:
    lo = min(23, max(0, _int_setting("scan.from_hour", DEFAULT_FROM_HOUR)))
    hi = min(24, max(lo + 1, _int_setting("scan.to_hour", DEFAULT_TO_HOUR)))
    return lo, hi


def _last_scan_at() -> float | None:
    try:
        v = store.get_setting(LAST_SCAN_AT)
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def due_now(now: float, last_at: float | None) -> bool:
    """True when a scan is owed: inside the day window and an interval since
    the last one. A Mac that slept through several hours scans once on waking,
    not once per missed hour."""
    hour = time.localtime(now).tm_hour
    lo, hi = window()
    if not (lo <= hour < hi):
        return False
    return last_at is None or now - last_at >= every_min() * 60


def next_scan_at(now: float | None = None) -> float:
    """When the next scan will start, for the dashboard."""
    now = now or time.time()
    last = _last_scan_at()
    t = max(now, (last or now) + every_min() * 60) if last else now
    lo, hi = window()
    lt = time.localtime(t)
    if lt.tm_hour >= hi or lt.tm_hour < lo:          # roll to the morning
        day = t if lt.tm_hour < lo else t + 86400
        d = time.localtime(day)
        t = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, lo, 0, 0, 0, 0, -1))
    return t


def stage_now(cap: int | None = None) -> int | None:
    """Start one scan. Returns the run id, or None when the browser is busy.

    No queue-depth gate any more: discovery already skips everything seen
    before, so an hourly scan adds only what was posted since — and a full queue
    is exactly when a fresh posting is worth seeing first.
    """
    if manager.busy() or store.get_active_run():
        return None
    options = {"channels": channels(), "mode": "dry",
               "cap": max(1, min(cap or _int_setting("scan.cap", DEFAULT_SCAN_CAP),
                                 config.MAX_CAP)),
               "geography": store.get_setting("run.geography") or "israel_remote",
               "strictness": store.get_setting("run.strictness") or "balanced",
               "concurrency": config.PREPARE_CONCURRENCY,
               # newest-first search: an hour's new postings are on page one
               "linkedin_pages": 1}
    run_id = store.create_run_atomic(options, "dry")
    if run_id is None:
        return None
    if not manager.start_prepare(run_id, options):
        store.update_run(run_id, status="error", message="manager busy")
        return None
    store.set_setting(LAST_SCAN_AT, str(time.time()))
    store.set_setting(LAST_STAGING, _today())
    store.set_setting(LAST_STAGING_RESULT, f"run #{run_id} scanning up to {options['cap']}")
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
    if due_now(time.time(), _last_scan_at()):
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
        "next_staging_at": time.strftime("%H:%M", time.localtime(next_scan_at())),
        "next_scan_ts": next_scan_at(),
        "last_scan_ts": _last_scan_at(),
        "every_min": every_min(),
        "window": list(window()),
        "last_verify": store.get_setting(LAST_VERIFY),
        "target_depth": target_depth(),
        "channels": channels(),
    }
