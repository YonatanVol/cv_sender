"""Send-path reliability: a stalled send must become finishable, and must never
be silently promoted to 'sent'."""
import time

import pytest

import cvsender.config as config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    return store


def _item(store, run_id, key="linkedin:acme:1", state="sending"):
    return store.add_item(run_id, {
        "channel": "linkedin", "company": "acme", "title": "SWE",
        "apply_url": "http://x", "dedupe_key": key, "content_hash": "h" + key,
        "state": state})


def test_stuck_sending_is_rescued_to_needs_input(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)
    # age it past the threshold
    db.set_item(iid, updated_at=time.time() - 3600)
    assert db.sweep_stuck_items(older_than_s=600) == 1
    it = db.get_item(iid)
    assert it["state"] == "needs_input"        # finishable, not lost
    assert "verify" in (it["reason"] or "").lower()


def test_stuck_sweep_never_marks_sent(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)
    db.set_item(iid, updated_at=time.time() - 3600)
    db.sweep_stuck_items(older_than_s=600)
    # no confirmation evidence exists, so nothing may be recorded as sent
    assert db.get_item(iid)["state"] != "sent"
    assert db.already_sent("linkedin:acme:1") is False


def test_recent_sending_is_left_alone(db):
    """A send genuinely in flight must not be yanked out from under the worker."""
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)                        # updated_at = now
    assert db.sweep_stuck_items(older_than_s=600) == 0
    assert db.get_item(iid)["state"] == "sending"


def test_rescued_item_appears_in_assist_queue(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)
    db.set_item(iid, updated_at=time.time() - 3600)
    assert not any(i["id"] == iid for i in db.assist_queue())  # hidden while 'sending'
    db.sweep_stuck_items(older_than_s=600)
    assert any(i["id"] == iid for i in db.assist_queue())      # now finishable
