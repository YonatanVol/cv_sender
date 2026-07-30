"""'Not available anymore': permanently stop offering a job, without ever
letting it look like it was sent."""
import pytest

import cvsender.config as config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    return store


def _item(db, run_id, key="greenhouse:acme:1"):
    return db.add_item(run_id, {
        "channel": "greenhouse", "company": "acme", "title": "SWE",
        "apply_url": "http://x", "dedupe_key": key, "content_hash": "h" + key,
        "state": "needs_input", "reason": "CAPTCHA present"})


def test_dismissed_job_is_not_restaged(db):
    run = db.create_run_atomic({}, "dry")
    iid = _item(db, run)
    item = db.get_item(iid)
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is False
    db.dismiss(item)
    # the prepare path uses already_handled -> it will now be skipped forever
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is True


def test_dismissed_never_counts_as_sent(db):
    """The whole point: it was never sent, so it must not pollute sent stats."""
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item)
    assert db.already_sent(item["dedupe_key"], item["content_hash"]) is False
    assert db.sent_today() == 0


def test_dismissed_leaves_the_assist_queue(db):
    run = db.create_run_atomic({}, "dry")
    iid = _item(db, run)
    assert any(i["id"] == iid for i in db.assist_queue())
    db.dismiss(db.get_item(iid))
    assert not any(i["id"] == iid for i in db.assist_queue())


def test_dismiss_matches_repost_by_content_hash(db):
    """Same role reposted under a new id shouldn't come back either."""
    run = db.create_run_atomic({}, "dry")
    db.dismiss(db.get_item(_item(db, run, "greenhouse:acme:1")))
    assert db.already_handled("greenhouse:acme:999", "hgreenhouse:acme:1") is True


def test_dismiss_is_idempotent(db):
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item)
    db.dismiss(item, kind="not_interested")     # re-dismiss must not blow up
    assert db.dismissed_count() == 1


def test_skip_is_not_permanent(db):
    """Skip means 'later' — unlike dismiss it must NOT block future staging."""
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.transition_item(item["id"], ["needs_input"], "skipped")
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is False
