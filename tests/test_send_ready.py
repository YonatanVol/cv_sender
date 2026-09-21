"""Work prepared by the morning search must be sendable.

The scheduler stages in DRY mode and a confirm is only allowed on a LIVE run,
so everything the morning search prepared was unreachable: four Greenhouse
applications sat ready, filled, with the CV attached, and could not be sent.
"""
import pytest

import cvsender.config as config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CVS_HOST", raising=False)
    from cvsender.db.migrations import migrate
    migrate()
    from fastapi.testclient import TestClient
    from cvsender import cloud, main, scheduler
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    monkeypatch.setattr(scheduler, "start", lambda: None)
    sent = []
    monkeypatch.setattr(main, "_ensure_send_worker", lambda run_id: sent.append(run_id))
    with TestClient(main.app) as c:
        yield c, sent


def _ready(store, run, n=1, state="ready"):
    return store.add_item(run, {"channel": "greenhouse", "company": f"c{n}",
                                "title": "Backend Engineer", "apply_url": "u",
                                "dedupe_key": f"gh:c{n}:{n}", "content_hash": f"h{n}",
                                "state": state})


def test_ready_items_from_a_dry_run_can_be_sent(client):
    c, sent = client
    from cvsender.db import store
    dry = store.create_run_atomic({}, "dry")
    ids = [_ready(store, dry, n) for n in range(3)]
    store.update_run(dry, status="awaiting_confirm")
    body = c.post("/api/send-ready", json={}).json()
    assert body["moved"] == 3 and body["sending"] == 3
    live = store.get_run(body["run_id"])
    assert live["mode"] == "live"
    assert all(store.get_item(i)["state"] == "sending" for i in ids)
    assert sent == [body["run_id"]]


def test_only_ready_items_move(client):
    c, _ = client
    from cvsender.db import store
    dry = store.create_run_atomic({}, "dry")
    ready = _ready(store, dry, 1)
    blocked = _ready(store, dry, 2, state="needs_input")
    store.update_run(dry, status="awaiting_confirm")
    body = c.post("/api/send-ready", json={}).json()
    assert body["sending"] == 1
    assert store.get_item(blocked)["state"] == "needs_input"
    assert store.get_item(blocked)["run_id"] == dry


def test_the_limit_is_respected(client):
    c, _ = client
    from cvsender.db import store
    dry = store.create_run_atomic({}, "dry")
    for n in range(6):
        _ready(store, dry, n)
    store.update_run(dry, status="awaiting_confirm")
    assert c.post("/api/send-ready", json={"limit": 2}).json()["sending"] == 2


def test_nothing_ready_is_not_an_error(client):
    c, sent = client
    body = c.post("/api/send-ready", json={}).json()
    assert body["sending"] == 0 and sent == []


def test_a_working_run_blocks_it(client):
    c, _ = client
    from cvsender.db import store
    dry = store.create_run_atomic({}, "dry")
    _ready(store, dry, 1)
    assert c.post("/api/send-ready", json={}).status_code == 409
