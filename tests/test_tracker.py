"""What happened after the send.

applications.stage was written once as 'applied' and never read; app_events was
created in migration 001 and never written. Sending is the middle of the story.
"""
import time

import pytest

import cvsender.config as config


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store as s
    migrate()
    return s


def _sent(store, company="Acme", days_ago=0, n=1):
    run = store.create_run_atomic({}, "live") or store.list_runs(1)[0]["id"]
    iid = store.add_item(run if isinstance(run, int) else run, {
        "channel": "linkedin", "company": company, "title": "Backend Engineer",
        "apply_url": "u", "dedupe_key": f"linkedin:{company}:{n}",
        "content_hash": f"h{n}", "state": "sent"})
    app_id = store.record_application(store.get_item(iid), '{"method":"dom"}')
    if days_ago:
        from cvsender.db.connection import tx
        with tx() as c:
            c.execute("UPDATE applications SET sent_at=? WHERE id=?",
                      (time.time() - days_ago * 86400, app_id))
    return app_id


def test_an_application_starts_applied_and_can_move(store):
    app_id = _sent(store)
    assert store.get_application(app_id)["stage"] == "applied"
    assert store.set_stage(app_id, "replied", "recruiter emailed") is True
    app = store.get_application(app_id)
    assert app["stage"] == "replied" and app["note"] == "recruiter emailed"
    assert store.set_stage(app_id, "interview") is True
    assert store.get_application(app_id)["stage"] == "interview"


def test_the_history_is_kept(store):
    app_id = _sent(store)
    store.set_stage(app_id, "replied")
    store.set_stage(app_id, "screen", "30 min call")
    kinds = [e["kind"] for e in store.app_events(app_id)]
    assert kinds == ["stage:replied", "stage:screen"]
    assert store.app_events(app_id)[1]["note"] == "30 min call"


def test_an_unknown_stage_changes_nothing(store):
    app_id = _sent(store)
    assert store.set_stage(app_id, "ghosted-ish") is False
    assert store.get_application(app_id)["stage"] == "applied"
    assert store.app_events(app_id) == []


def test_followups_are_due_after_a_week_and_only_while_applied(store):
    fresh = _sent(store, "Fresh", days_ago=2, n=1)
    old = _sent(store, "Old", days_ago=9, n=2)
    answered = _sent(store, "Answered", days_ago=20, n=3)
    store.set_stage(answered, "replied")
    due = [a["id"] for a in store.followups_due()]
    assert old in due and fresh not in due and answered not in due


def test_snoozing_pushes_a_followup_out(store):
    app_id = _sent(store, "Old", days_ago=30)
    assert app_id in [a["id"] for a in store.followups_due()]
    store.snooze_followup(app_id, days=7)
    assert app_id not in [a["id"] for a in store.followups_due()]


def test_the_app_never_sends_a_followup_itself(store):
    """It records that Yonatan sent one. Nothing here contacts anybody."""
    app_id = _sent(store, "Old", days_ago=10)
    store.add_app_event(app_id, "followup", "sent by hand")
    assert [e["kind"] for e in store.app_events(app_id)] == ["followup"]
    assert store.get_application(app_id)["stage"] == "applied"


def test_funnel_counts_every_stage(store):
    a, b = _sent(store, "A", n=1), _sent(store, "B", n=2)
    store.set_stage(b, "interview")
    counts = store.funnel_counts()
    assert counts["applied"] == 1 and counts["interview"] == 1
    assert set(counts) == set(store.STAGES)


def test_tracker_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t2.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CVS_HOST", raising=False)
    from cvsender.db.migrations import migrate
    migrate()
    from cvsender.db import store as s
    app_id = _sent(s, "Acme", days_ago=10)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main, scheduler
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    monkeypatch.setattr(scheduler, "start", lambda: None)
    with TestClient(main.app) as c:
        assert c.get("/applications").status_code == 200
        body = c.get("/api/applications").json()
        assert body["applications"][0]["followup_due"] is True
        assert body["funnel"]["applied"] == 1
        assert c.post(f"/api/applications/{app_id}/stage",
                      json={"stage": "interview"}).json()["application"]["stage"] == "interview"
        assert c.post(f"/api/applications/{app_id}/stage",
                      json={"stage": "nonsense"}).status_code == 400
        assert c.post(f"/api/applications/{app_id}/followup", json={}).json()["logged"] is True
