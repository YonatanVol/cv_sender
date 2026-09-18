"""LinkedIn volume ceiling: automating LinkedIn is against its User Agreement,
so the cap must hold against settings, scripts and restored cloud backups."""
import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender.engine import worker
    migrate()
    return store, worker


def _sent(store, n, _run=[]):
    if not _run:
        _run.append(store.create_run_atomic({}, "live"))
    run = _run[0]
    for i in range(n):
        key = f"linkedin:c{len(store.list_items(run))}-{i}:{i}"
        iid = store.add_item(run, {"channel": "linkedin", "company": f"c{i}", "title": "t",
                                   "apply_url": "u", "dedupe_key": key, "content_hash": key,
                                   "state": "needs_input"})
        store.record_application({**store.get_item(iid), "channel": "linkedin"}, "{}")


def test_default_cap(env):
    store, worker = env
    assert worker.linkedin_daily_cap() == config.LINKEDIN_DAILY_CAP
    assert worker.linkedin_cap_left() == config.LINKEDIN_DAILY_CAP


def test_setting_can_lower_but_never_raise(env):
    store, worker = env
    store.set_setting("linkedin.daily_cap", "5")
    assert worker.linkedin_daily_cap() == 5
    store.set_setting("linkedin.daily_cap", "500")           # script or bad restore
    assert worker.linkedin_daily_cap() == config.LINKEDIN_CAP_CEILING
    store.set_setting("linkedin.daily_cap", "not a number")
    assert worker.linkedin_daily_cap() == config.LINKEDIN_DAILY_CAP
    store.set_setting("linkedin.daily_cap", "-3")
    assert worker.linkedin_daily_cap() == 0


def test_cap_counts_todays_sends(env):
    store, worker = env
    store.set_setting("linkedin.daily_cap", "3")
    _sent(store, 2)
    assert worker.linkedin_cap_left() == 1
    _sent(store, 1)
    assert worker.linkedin_cap_left() == 0
