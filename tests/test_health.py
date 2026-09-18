"""Health rows: every silent failure this system has actually had."""
import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LINKEDIN_PROFILE_DIR", tmp_path / "li")
    from cvsender.db.migrations import migrate
    from cvsender import health
    migrate()
    return health


def test_missing_browser_is_a_failure_with_a_fix(env, monkeypatch):
    """The macOS update deleted Playwright's Chromium; this must be loud."""
    import cvsender.health as health
    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: (_ for _ in ()).throw(RuntimeError("no executable")))
    row = health.browser_engine()
    assert row["state"] == health.FAIL and "playwright install" in row["fix"]


def test_missing_linkedin_session_is_reported(env):
    row = env.linkedin_session()
    assert row["state"] in (env.WARN, env.FAIL) and "li_v2_login" in row["fix"]


def test_missing_profile_is_a_failure(env):
    assert env.profile_row()["state"] == env.FAIL


def test_report_never_raises_and_summarises(env, monkeypatch):
    monkeypatch.setattr(env, "CHECKS", (lambda: (_ for _ in ()).throw(ValueError("x")),
                                        lambda: env._row("fine", env.OK, "yes")))
    rep = env.report()
    assert rep["state"] in (env.OK, env.WARN, env.FAIL)
    assert len(rep["checks"]) == 2


def test_scheduler_row_reads_the_database_not_this_process(env, monkeypatch):
    """The doctor runs in a terminal; the server ticks in another process."""
    import time
    from cvsender.db import store
    from cvsender import scheduler
    store.set_setting(scheduler.LAST_TICK, str(time.time()))
    assert env.scheduler_row()["state"] == env.OK
    store.set_setting(scheduler.LAST_TICK, str(time.time() - 3600))
    row = env.scheduler_row()
    assert row["state"] == env.FAIL and "stalled" in row["detail"]
    store.set_setting(scheduler.LAST_TICK, None)
    assert env.scheduler_row()["state"] == env.FAIL


def test_health_endpoint_and_run_now(tmp_path, monkeypatch):
    """The app exposes the same rows the doctor prints, plus on-demand staging."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CVS_HOST", raising=False)
    from cvsender.db.migrations import migrate
    migrate()
    from fastapi.testclient import TestClient
    from cvsender import cloud, main, scheduler
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    # No network in tests: cloud_row() would otherwise call Supabase, which
    # makes the suite fail on a slow link or offline.
    monkeypatch.setattr(cloud, "status", lambda: {"enabled": True, "connected": True,
                                                  "url": "x", "error": ""})
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "stage_now", lambda cap=None: 42)
    with TestClient(main.app) as c:
        assert c.get("/healthz").json() == {"ok": True}
        body = c.get("/api/health").json()
        assert body["state"] in ("ok", "warn", "fail")
        assert {r["check"] for r in body["checks"]} >= {"profile", "browser engine", "queue"}
        assert c.post("/api/run-now").json()["run_id"] == 42


def test_cloud_row_offline_is_a_failure_not_a_crash(env, monkeypatch):
    """A paused or unreachable project must show as a red row, never an error."""
    from cvsender import cloud
    monkeypatch.setattr(cloud, "status", lambda: {"enabled": True, "connected": False,
                                                  "url": "x", "error": "ConnectError"})
    row = env.cloud_row()
    assert row["state"] == env.FAIL and "pauses after 7 idle days" in row["fix"]
