"""The scheduler keeps the queue stocked without anyone starting it — and must
never send, never fight the browser, and never stage twice in a day."""
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


def _day(h, m, day="2026-09-20"):
    return time.strptime(f"{day} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")


def test_due_only_after_the_hour_and_once_a_day(env):
    sched, store, _, _ = env
    today = time.strftime("%Y-%m-%d")
    assert sched.due_now(_day(7, 0, today), None) is False       # too early
    assert sched.due_now(_day(8, 30, today), None) is True       # on time
    assert sched.due_now(_day(13, 0, today), None) is True       # catch-up
    assert sched.due_now(_day(22, 0, today), None) is False      # too late
    assert sched.due_now(_day(9, 0, today), today) is False      # already staged


def test_staging_respects_the_target_and_never_sends(env):
    sched, store, started, _ = env
    store.set_setting("run.target", "3")
    run_id = sched.stage_now()
    assert run_id is not None and started[0][1]["mode"] == "dry"
    assert started[0][1]["cap"] == 3
    assert store.get_run(run_id)["mode"] == "dry"


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


def test_status_reports_what_the_doctor_prints(env):
    sched, store, _, _ = env
    store.set_setting("run.target", "120")
    st = sched.status()
    assert st["enabled"] is True and st["target_depth"] == 120
    assert st["next_staging_at"] == "08:30"
