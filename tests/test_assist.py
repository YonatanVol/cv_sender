"""Assist-mode + AnswerBank: the features that convert blocked applications
into real sends. These guard the invariants that matter most — a send is only
ever recorded once, and a learned answer is reused."""
import pytest

import cvsender.config as config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    return store


def _item(store, run_id, key="greenhouse:acme:1", state="needs_input"):
    return store.add_item(run_id, {
        "channel": "greenhouse", "company": "acme", "title": "SWE",
        "apply_url": "http://x", "dedupe_key": key, "content_hash": "h" + key,
        "state": state, "reason": "CAPTCHA present"})


# ------------------------------ answer bank --------------------------------

def test_answer_learned_once_is_recalled(db):
    db.learn_answer("How many years of experience with Python?*", "2")
    # punctuation / case / spacing differences still hit the same entry
    assert db.recall_answer("how many years of experience with python?") == "2"
    assert db.recall_answer("  How Many Years Of Experience With Python  ") == "2"


def test_unknown_question_returns_none(db):
    assert db.recall_answer("what is your favourite colour") is None


def test_answerbank_feeds_known_answer(db, monkeypatch):
    from cvsender.engine import answerbank as ab
    db.learn_answer("Do you have a security clearance?", "No")
    # known_answer consults the DB before falling back to built-in rules
    assert ab.known_answer("Do you have a security clearance?", {}) == "No"


def test_prohibited_never_stored_or_answered(db):
    from cvsender.engine import answerbank as ab
    db.learn_answer("Password", "hunter2")          # must never be persisted
    assert db.recall_answer("Password") is None     # refused at write time
    assert ab.known_answer("Password", {}) is None
    assert ab.known_answer("Bank account number", {}) is None
    assert ab.known_answer("תעודת זהות", {}) is None


def test_eeo_never_fabricated(db):
    from cvsender.engine import answerbank as ab
    assert ab.known_answer("What is your gender?", {}) == "Decline To Self Identify"


# ------------------------------ assist queue -------------------------------

def test_assist_queue_lists_finishable_and_hides_sent(db):
    run = db.create_run_atomic({}, "live")
    blocked = _item(db, run, "greenhouse:acme:1")
    done = _item(db, run, "greenhouse:acme:2")
    assert len(db.assist_queue()) == 2
    # once an application is recorded, it drops out of the queue
    db.transition_item(done, ["needs_input"], "sent")
    db.record_application(db.get_item(done), '{"method":"user"}')
    keys = [i["id"] for i in db.assist_queue()]
    assert blocked in keys and done not in keys


def test_sent_today_counts_real_applications(db):
    """Every send path writes an application; the badge counts those, so
    automatic LinkedIn sends show up and a duplicate never double-counts."""
    assert db.sent_today() == 0
    run = db.create_run_atomic({}, "live")
    keys = [("linkedin:a:1", "linkedin"), ("linkedin:b:2", "linkedin"),
            ("greenhouse:c:3", "greenhouse")]
    items = []
    for key, channel in keys:
        iid = _item(db, run, key=key)
        items.append({**db.get_item(iid), "channel": channel})
    for it in items:
        db.record_application(it, '{"method":"dom"}')
    db.record_application(items[0], '{"method":"dom"}')        # duplicate
    assert db.sent_today("linkedin") == 2
    assert db.sent_today() == 3


def test_user_confirmed_send_is_recorded_once(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run)
    db.transition_item(iid, ["needs_input"], "sent")
    item = db.get_item(iid)
    db.record_application(item, '{"method":"user"}')
    db.record_application(item, '{"method":"user"}')   # idempotent
    assert db.already_sent(item["dedupe_key"]) is True


def test_recently_parked_posting_is_not_restaged(db):
    run = db.create_run_atomic({}, "live")
    iid = _item(db, run, key="linkedin:acme:9")            # needs_input now
    assert db.waiting_in_queue("linkedin:acme:9") is True
    assert db.waiting_in_queue("linkedin:other:1") is False
    db.transition_item(iid, ["needs_input"], "skipped")
    assert db.waiting_in_queue("linkedin:acme:9") is False  # no longer parked
    db.transition_item(iid, ["skipped"], "needs_input")
    from cvsender.db.connection import tx
    with tx() as c:                                         # parked 8 days ago
        c.execute("UPDATE run_items SET updated_at = updated_at - 8*86400 WHERE id=?", (iid,))
    assert db.waiting_in_queue("linkedin:acme:9") is False  # parked, but stale
