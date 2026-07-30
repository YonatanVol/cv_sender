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


def test_daily_counter(db):
    assert db.sent_today() == 0
    db.bump_daily("linkedin")
    db.bump_daily("linkedin")
    db.bump_daily("greenhouse")
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
