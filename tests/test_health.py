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
