"""Per-role CVs: the posting picks the CV, and the choice is recorded.

Nothing here invents CV content — it selects among files that were built once
from the same true history and reviewed.
"""
import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender import cv_tailor
    migrate()
    paths = {}
    for name in ("general", "backend", "fullstack", "qa", "data"):
        p = tmp_path / f"cv_{name}.pdf"
        p.write_bytes(b"%PDF-1.7 " + name.encode())
        paths[name] = str(p)
        store.upsert_cv_variant(name, name.title(), str(p), cv_tailor.sha256(str(p)),
                                [name], 2, is_default=(name == "general"))
    return cv_tailor, store, paths


@pytest.mark.parametrize("title,expected", [
    ("Junior Backend Engineer (Python, FastAPI)", "backend"),
    ("Backend Developer — Go", "backend"),
    ("Full Stack Developer React / Node", "fullstack"),
    ("Frontend Engineer, TypeScript", "fullstack"),
    ("QA Automation Engineer", "qa"),
    ("SDET — Test Automation", "qa"),
    ("Data Analyst (SQL)", "data"),
    ("Data Engineer, ETL", "data"),
])
def test_the_posting_picks_the_cv(env, title, expected):
    cv_tailor, _, paths = env
    path, name = cv_tailor.cv_for(title)
    assert name == expected and path == paths[expected]


@pytest.mark.parametrize("title", ["Software Engineer", "מפתח/ת תוכנה",
                                   "Engineer", "Junior Developer"])
def test_unclear_postings_get_the_default(env, title):
    cv_tailor, _, paths = env
    assert cv_tailor.cv_for(title) == (paths["general"], "general")


def test_a_tie_never_guesses(env):
    """Backend and QA equally called for: send the general CV, don't gamble."""
    cv_tailor, _, paths = env
    _, name = cv_tailor.cv_for("Backend QA")
    assert name == "general"


def test_description_counts_less_than_the_title(env):
    cv_tailor, _, _ = env
    _, name = cv_tailor.cv_for("Backend Engineer",
                               "you will write cypress tests and testing docs")
    assert name == "backend"


def test_no_variants_means_no_choice(env, monkeypatch):
    cv_tailor, store, _ = env
    for name in ("general", "backend", "fullstack", "qa", "data"):
        store.delete_cv_variant(name)
    assert cv_tailor.cv_for("Backend Engineer") == ("", "")


def test_a_missing_file_is_never_offered(env):
    cv_tailor, store, paths = env
    from pathlib import Path
    Path(paths["backend"]).unlink()
    _, name = cv_tailor.cv_for("Backend Engineer (Python)")
    assert name == "general"


def test_the_application_records_which_cv_was_sent(env):
    cv_tailor, store, paths = env
    run = store.create_run_atomic({}, "live")
    iid = store.add_item(run, {"channel": "linkedin", "company": "a", "title": "Backend",
                               "apply_url": "u", "dedupe_key": "linkedin:a:1",
                               "content_hash": "h", "state": "needs_input"})
    item = store.get_item(iid)
    store.record_application(item, "{}", cv_variant="backend",
                             cv_sha256=cv_tailor.sha256(paths["backend"]))
    import sqlite3
    from cvsender.db.connection import ro
    with ro() as c:
        row = dict(c.execute("SELECT cv_variant, cv_sha256 FROM applications").fetchone())
    assert row["cv_variant"] == "backend" and len(row["cv_sha256"]) == 64


def test_the_send_guard_compares_the_variant_actually_attached(env):
    """The guard must hash the file that was attached, not the profile's CV."""
    cv_tailor, store, paths = env
    from cvsender.channels.base import SendHandle
    from cvsender.engine.worker import _cv_guard
    handle = SendHandle(dedupe_key="k", channel="linkedin", apply_url="u",
                        company="c", title="t", answers={},
                        cv_path=paths["backend"],
                        cv_sha256=cv_tailor.sha256(paths["backend"]))
    assert _cv_guard(handle, {"cv_path": paths["general"],
                              "cv_sha256": cv_tailor.sha256(paths["general"])}) == ""
    from pathlib import Path
    Path(paths["backend"]).write_bytes(b"%PDF-1.7 edited")
    assert "changed" in _cv_guard(handle, {})


def test_variants_endpoint_lists_them(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CVS_HOST", raising=False)
    from cvsender.db.migrations import migrate
    migrate()
    from cvsender.db import store
    p = tmp_path / "cv.pdf"; p.write_bytes(b"%PDF-1.7")
    store.upsert_cv_variant("backend", "Backend", str(p), "abc", ["backend"], 2, True)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main, scheduler
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    monkeypatch.setattr(scheduler, "start", lambda: None)
    with TestClient(main.app) as c:
        body = c.get("/api/cv/variants").json()
    assert body["variants"][0]["name"] == "backend"
    assert body["variants"][0]["is_default"] == 1


def test_a_verified_send_records_the_application_and_its_cv(env):
    """Regression: _apply_send_result referenced an undefined name, so the first
    real send after the per-role CV change would have raised NameError *after*
    the item was marked sent — no application row, no dedupe, run dead."""
    import json
    from cvsender.channels.base import ConfirmationEvidence, SendResult, SENT
    from cvsender.db import store
    from cvsender.engine import worker
    cv_tailor, store_mod, paths = env
    run = store.create_run_atomic({}, "live")
    iid = store.add_item(run, {"channel": "linkedin", "company": "acme", "title": "Backend",
                               "apply_url": "u", "dedupe_key": "linkedin:acme:1",
                               "content_hash": "h", "state": "sending"})
    store.transition_item(iid, ["sending"], "sending", result_json=json.dumps(
        {"handle": {"cv_variant": "backend", "cv_sha256": "a" * 64}}))
    res = SendResult(state=SENT, evidence=ConfirmationEvidence("dom", matched="sent", at=1.0))
    worker._apply_send_result(run, store.get_item(iid), res)      # must not raise
    assert store.get_item(iid)["state"] == "sent"
    from cvsender.db.connection import ro
    with ro() as c:
        row = dict(c.execute("SELECT cv_variant, cv_sha256 FROM applications").fetchone())
    assert row["cv_variant"] == "backend" and row["cv_sha256"] == "a" * 64
    assert store.sent_today() == 1
