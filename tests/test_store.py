"""State-model invariants that fix v1's dedupe / stuck-run bugs."""
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


def _item(store, run_id, key="greenhouse:acme:1", state="ready"):
    return store.add_item(run_id, {
        "channel": "greenhouse", "company": "acme", "title": "SWE",
        "apply_url": "http://x", "dedupe_key": key, "content_hash": "h1",
        "state": state})


def test_single_active_run_is_atomic(db):
    r1 = db.create_run_atomic({}, "dry")
    r2 = db.create_run_atomic({}, "dry")     # a run is already active
    assert r1 is not None and r2 is None


def test_guarded_transition_blocks_double(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run, state="ready")
    assert db.transition_item(iid, ["ready"], "sending") is True
    # second click / second tab: already left 'ready' -> no-op
    assert db.transition_item(iid, ["ready"], "sending") is False


def test_only_verified_sent_is_terminal(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)
    # needs_input must NOT block re-offering (v1 made it terminal)
    db.transition_item(iid, ["ready"], "needs_input", reason="captcha")
    assert db.already_sent("greenhouse:acme:1", "h1") is False
    # only a recorded application (with evidence) is terminal
    db.transition_item(iid, ["needs_input"], "sending")
    db.transition_item(iid, ["sending"], "sent")
    item = db.get_item(iid)
    db.record_application(item, evidence='{"method":"network"}')
    assert db.already_sent("greenhouse:acme:1") is True
    # cross-channel repost caught by content_hash
    assert db.already_sent("lever:acme:99", "h1") is True


def test_dedupe_within_run(db):
    run = db.create_run_atomic({}, "dry")
    assert _item(db, run) is not None
    assert _item(db, run) is None            # same (run_id, dedupe_key)


def test_sweep_recovers_stale_run(db):
    run = db.create_run_atomic({}, "live")
    prep = _item(db, run, key="k-prep", state="preparing")
    send = _item(db, run, key="k-send", state="sending")
    ready = _item(db, run, key="k-ready", state="ready")
    db.update_run(run, heartbeat_at=time.time() - 999, worker_pid=999999)
    swept = db.sweep_stale_runs(stale_after_s=30)
    assert run in swept
    assert db.get_item(prep)["state"] == "queued"        # re-preparable
    assert db.get_item(send)["state"] == "needs_input"   # never auto-sent
    assert db.get_item(ready)["state"] == "ready"        # durable, kept
    assert db.get_run(run)["status"] == "interrupted"


def test_events_cursor(db):
    run = db.create_run_atomic({}, "dry")
    e1 = db.add_event(run, "phase", "one")
    e2 = db.add_event(run, "phase", "two")
    after = db.events_after(run, e1)
    assert len(after) == 1 and after[0]["id"] == e2
