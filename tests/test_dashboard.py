"""The dashboard: the machine scans every hour, Yonatan sends by hand.

It must show what is ready with the CV and address each will carry, never send
on its own, and say plainly when a scan holds the browser.
"""
import json, time

import pytest

import cvsender.config as config


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender import main, auth
    migrate()
    store.save_profile({"full_name": "Y", "email": "y@x.com", "location": "Tel Aviv, Israel"})
    monkeypatch.setattr(main, "_cloud_bg", lambda *a, **k: None)
    monkeypatch.setattr(main.scheduler, "start", lambda: None)
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    c.cookies.set("cvs_session", auth.create_session())
    return c, store


def _ready(store, run_id, company, cv="backend", address="Zichron Ya'akov, Israel",
           channel="linkedin", score=80):
    iid = store.add_item(run_id, {
        "channel": channel, "company": company, "title": "Software Engineer",
        "location": "Haifa, Israel", "url": "u", "apply_url": f"https://x/{company}",
        "dedupe_key": f"{channel}:{company}:1", "content_hash": company,
        "score": score, "score_json": {"band": "strong fit",
                                       "reasons": [{"label": "junior role", "points": 20}]},
        "identity": f"{company}|se|haifa", "first_seen_at": time.time() - 600,
        "state": "queued"})
    store.transition_item(iid, ["queued"], "preparing")
    store.transition_item(iid, ["preparing"], "ready", reason="ready (reached submit)")
    with store.tx() as c:
        c.execute("UPDATE run_items SET result_json=? WHERE id=?", (json.dumps({
            "handle": {"cv_variant": cv, "answers": {"location": address}}}), iid))
    return iid


def test_dashboard_shows_what_each_application_will_carry(app):
    c, store = app
    rid = store.create_run_atomic({"channels": ["linkedin"]}, "dry")
    store.update_run(rid, status="awaiting_confirm")
    _ready(store, rid, "maytronics")
    d = c.get("/api/dashboard").json()
    r = d["ready"][0]
    assert r["company"] == "maytronics"
    assert r["cv"] == "backend" and r["address"] == "Zichron Ya'akov, Israel"
    assert r["band"] == "strong fit" and r["reasons"] == ["junior role"]
    assert r["found_min_ago"] == 10


def test_dashboard_never_sends_on_its_own(app):
    c, store = app
    rid = store.create_run_atomic({"channels": ["linkedin"]}, "dry")
    store.update_run(rid, status="awaiting_confirm")
    _ready(store, rid, "a")
    for _ in range(3):
        c.get("/api/dashboard")
    assert store.sent_today() == 0
    assert c.get("/api/dashboard").json()["ready"][0]["company"] == "a"


def test_the_scan_in_progress_is_reported(app):
    c, store = app
    rid = store.create_run_atomic({"channels": ["linkedin"]}, "dry")
    d = c.get("/api/dashboard").json()
    assert d["scan"]["running"]["id"] == rid


def test_hourly_scanning_can_be_paused_and_resumed(app):
    c, store = app
    assert c.post("/api/scan/toggle", json={"enabled": False}).json()["enabled"] is False
    assert c.get("/api/dashboard").json()["scan"]["enabled"] is False
    assert c.get("/api/dashboard").json()["scan"]["next_ts"] is None
    assert c.post("/api/scan/toggle", json={"enabled": True}).json()["enabled"] is True


def test_home_is_the_dashboard(app):
    c, _ = app
    assert "Ready to send" in c.get("/").text
    assert c.get("/console").status_code == 200
