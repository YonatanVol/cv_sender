"""The scheduler scans for new postings every hour of the day without anyone
starting it — and must never send, never fight the browser, and never scan
overnight. Sending is Yonatan's button."""
import time

import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender import scheduler
    migrate()
    store.save_profile({"full_name": "Y", "email": "y@x.com", "cv_path": str(tmp_path / "cv.pdf")})
    started = []

    class FakeManager:
        def __init__(self): self._busy = False
        def busy(self): return self._busy
        def start_prepare(self, run_id, options):
            started.append((run_id, options)); return True
    fake = FakeManager()
    monkeypatch.setattr(scheduler, "manager", fake)
    return scheduler, store, started, fake


def _at(h, m, day="2026-10-05"):
    return time.mktime(time.strptime(f"{day} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M"))


def test_scans_every_hour_inside_the_day(env):
    sched, store, _, _ = env
    assert sched.due_now(_at(9, 0), None) is True                  # never scanned
    assert sched.due_now(_at(9, 30), _at(9, 0)) is False           # 30 min later
    assert sched.due_now(_at(10, 0), _at(9, 0)) is True            # an hour later
    assert sched.due_now(_at(22, 59), _at(21, 50)) is True         # last slot


def test_never_scans_overnight(env):
    """Sending is manual, so a 03:00 posting waits for the morning anyway, and
    every scan is LinkedIn traffic on his account."""
    sched, store, _, _ = env
    assert sched.due_now(_at(23, 30), _at(21, 0)) is False
    assert sched.due_now(_at(3, 0), None) is False
    assert sched.due_now(_at(6, 59), _at(22, 0, "2026-10-04")) is False
    assert sched.due_now(_at(7, 0), _at(22, 0, "2026-10-04")) is True


def test_a_mac_that_slept_scans_once_not_once_per_missed_hour(env):
    sched, store, started, _ = env
    store.set_setting(sched.LAST_SCAN_AT, str(_at(9, 0)))
    assert sched.due_now(_at(15, 0), _at(9, 0)) is True            # owed
    sched.stage_now()
    last = float(store.get_setting(sched.LAST_SCAN_AT))
    assert sched.due_now(last + 60, last) is False                 # and only once


def test_interval_and_window_are_settings(env):
    sched, store, _, _ = env
    store.set_setting("scan.every_min", "30")
    store.set_setting("scan.from_hour", "0")
    store.set_setting("scan.to_hour", "24")
    assert sched.due_now(_at(3, 0), _at(2, 29)) is True
    assert sched.every_min() == 30 and sched.window() == (0, 24)


def test_the_interval_has_a_floor(env):
    """A typo of '1' must not mean a LinkedIn search every minute."""
    sched, store, _, _ = env
    store.set_setting("scan.every_min", "1")
    assert sched.every_min() == 10


def test_linkedin_is_scanned_by_default_and_first(env):
    """The old default was the job boards only — the channels that almost never
    finish an application — so nothing was sent for 13 days."""
    sched, store, started, _ = env
    sched.stage_now()
    chans = started[0][1]["channels"]
    assert chans[0] == "linkedin" and "greenhouse" in chans


def test_a_scan_never_sends_and_reads_one_page(env):
    sched, store, started, _ = env
    run_id = sched.stage_now()
    opts = started[0][1]
    assert opts["mode"] == "dry" and store.get_run(run_id)["mode"] == "dry"
    assert opts["linkedin_pages"] == 1                 # newest-first: page one
    assert opts["cap"] == 30


def test_a_full_queue_does_not_stop_the_scan(env):
    """A full queue is exactly when a fresh posting is worth seeing first."""
    sched, store, started, _ = env
    store.set_setting("run.target", "0")
    assert sched.stage_now() is not None


def test_no_staging_while_the_browser_is_busy(env):
    sched, store, started, fake = env
    fake._busy = True
    assert sched.stage_now() is None and started == []


def test_no_staging_when_a_run_is_already_active(env):
    sched, store, started, _ = env
    store.create_run_atomic({}, "dry")
    assert sched.stage_now() is None and started == []


def test_tick_records_a_heartbeat_and_purges_sessions(env):
    sched, store, _, _ = env
    store.create_session("hash", -10)                     # already expired
    out = sched.tick()
    assert out["purged"] == 1
    assert store.get_setting(sched.LAST_TICK) is not None


def test_disabled_scheduler_does_nothing(env):
    sched, store, started, _ = env
    store.set_setting(sched.ENABLED, "0")
    assert sched.tick()["staged"] is None and started == []


def test_the_loop_survives_a_failing_tick(env, monkeypatch):
    """A bad tick must never kill the thread: the morning run depends on it."""
    import threading
    sched, store, _, _ = env
    monkeypatch.setattr(sched, "tick",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    stop = threading.Event()

    class OnceThenStop(threading.Event):
        def wait(self, timeout=None):
            stop.set()
            return True
        def is_set(self):
            return stop.is_set()
    sched._loop(OnceThenStop())                       # must return, not raise
    assert "boom" in (store.get_setting(sched.LAST_STAGING_RESULT) or "")


def test_status_reports_what_the_dashboard_shows(env):
    sched, store, _, _ = env
    st = sched.status()
    assert st["enabled"] is True and st["every_min"] == 60
    assert st["window"] == [7, 23]
    assert st["channels"][0] == "linkedin"
    assert len(st["next_staging_at"]) == 5            # HH:MM


def test_a_parked_run_never_blocks_the_next_staging(env):
    """A finished prepare sits in 'awaiting_confirm' until a human looks at it.
    That must not stop tomorrow's morning run."""
    sched, store, started, _ = env
    first = sched.stage_now()
    store.update_run(first, status="awaiting_confirm")
    assert store.get_active_run() is None
    assert store.parked_run()["id"] == first
    second = sched.stage_now()
    assert second is not None and second != first


# ------------------- LinkedIn gets the cap before the boards ----------------

def test_linkedin_is_prepared_before_the_job_boards(env, monkeypatch):
    """Both share one cap. The boards used to run first, so a scan that found
    forty Greenhouse postings left LinkedIn — the channel that sends — none."""
    import asyncio
    from cvsender.engine import worker

    calls = []

    async def fake_li(run_id, options, cancel, cap, profile, cv_path):
        calls.append(("linkedin", cap)); return cap - 25

    async def fake_ats(run_id, options, cancel, cap, profile, cv_path, channels):
        calls.append(("ats", cap)); return 0

    monkeypatch.setattr(worker, "_prepare_linkedin", fake_li)
    monkeypatch.setattr(worker, "_prepare_ats", fake_ats)
    sched, store, _, _ = env
    run_id = store.create_run_atomic({"channels": ["linkedin", "greenhouse"]}, "dry")

    class Cancel:
        def check(self): pass

    asyncio.run(worker.run_prepare(run_id, {"channels": ["linkedin", "greenhouse"],
                                            "cap": 30}, Cancel()))
    assert calls == [("linkedin", 30), ("ats", 5)]
