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


def test_same_posting_blocked_permanently(db):
    """Same channel+external id must stay blocked, however long it's been."""
    import time as _t
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item)
    with db.tx() as c:                        # pretend a year passed
        c.execute("UPDATE dismissed SET at=?, content_expires_at=?",
                  (_t.time() - 365 * 86400, _t.time() - 300 * 86400))
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is True


def test_same_canonical_url_blocked_permanently(db):
    """Tracking params / trailing slash must not defeat the block."""
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item)                          # apply_url = http://x
    assert db.is_dismissed("greenhouse:acme:777", None,
                           "http://X/?utm_source=foo") is True


def test_content_only_match_expires(db):
    """A closed role reposted later with identical text MUST resurface —
    blocking forever on content alone would hide a genuinely new opening."""
    import time as _t
    run = db.create_run_atomic({}, "dry")
    db.dismiss(db.get_item(_item(db, run, "greenhouse:acme:1")))
    # different posting id and URL, same text -> blocked for now...
    assert db.is_dismissed("greenhouse:acme:999", "hgreenhouse:acme:1",
                           "http://other") is True
    with db.tx() as c:                        # ...but the window expires
        c.execute("UPDATE dismissed SET content_expires_at=?",
                  (_t.time() - 10,))
    assert db.is_dismissed("greenhouse:acme:999", "hgreenhouse:acme:1",
                           "http://other") is False


def test_restore_undoes_dismissal(db):
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item)
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is True
    assert db.restore_dismissed(item["dedupe_key"]) is True
    assert db.already_handled(item["dedupe_key"], item["content_hash"]) is False
    assert db.dismissed_count() == 0


def test_dismissal_records_audit_details(db):
    run = db.create_run_atomic({}, "dry")
    item = db.get_item(_item(db, run))
    db.dismiss(item, kind="unavailable", note="posting closed")
    row = db.list_dismissed()[0]
    assert row["at"] and row["kind"] == "unavailable"
    assert row["note"] == "posting closed"
    assert row["channel"] == "greenhouse" and row["external_id"] == "1"
    assert row["canonical_url"] == "http://x"


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
