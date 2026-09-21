"""Today answers one question: what should I do in the next five minutes.

Every number must come from the database — a screen that guesses is worse than
no screen, because it is trusted.
"""
import json

import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LINKEDIN_PROFILE_DIR", tmp_path / "li")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender import cloud, console, today
    migrate()
    monkeypatch.setattr(cloud, "status", lambda: {"enabled": True, "connected": True,
                                                  "url": "x", "error": ""})
    store.save_profile({"full_name": "Y", "email": "y@x.com",
                        "cv_path": str(tmp_path / "cv.pdf")})
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.7")
    return store, today, console


def _item(store, run, **kw):
    base = {"channel": "greenhouse", "company": "Acme", "title": "Backend Engineer",
            "apply_url": "https://x/jobs/1", "dedupe_key": f"gh:acme:{kw.get('n', 1)}",
            "content_hash": f"h{kw.get('n', 1)}", "state": "needs_input",
            "score": 70, "score_json": {"score": 70, "band": "possible fit",
                                        "explain": "70 possible fit — backend +8",
                                        "reasons": [{"label": "backend", "points": 8}]}}
    base.update({k: v for k, v in kw.items() if k != "n"})
    return store.add_item(run, base)


def test_next_action_prefers_finishing_something_ready(env):
    store, today, _ = env
    run = store.create_run_atomic({}, "live")
    _item(store, run, n=1, state="needs_input", block_kind="captcha")
    _item(store, run, n=2, state="ready", company="Ready Co", score=90,
          score_json={"score": 90, "band": "excellent fit", "explain": "90", "reasons": []})
    s = today.snapshot()
    assert s["next"]["kind"] == "send"
    assert s["next"]["item"]["company"] == "Ready Co"


def test_next_action_prefers_the_answer_that_unblocks_the_most(env):
    store, today, _ = env
    run = store.create_run_atomic({}, "dry")
    q = {"label": "How many years with Python?", "kind": "text", "options": []}
    for i in range(3):
        iid = _item(store, run, n=i, state="needs_input", block_kind="question")
        store.transition_item(iid, ["needs_input"], "needs_input",
                              result_json=json.dumps({"questions": [q]}))
    s = today.snapshot()
    assert s["next"]["kind"] == "answer"
    assert s["next"]["blocking"] == 3


def test_an_empty_queue_says_so_instead_of_inventing_work(env):
    _, today, _ = env
    s = today.snapshot()
    assert s["next"] is None and s["counts"]["total"] == 0
    assert s["goal"]["done"] == 0


def test_counts_match_the_database(env):
    store, today, _ = env
    run = store.create_run_atomic({}, "dry")
    _item(store, run, n=1, block_kind="captcha")
    _item(store, run, n=2, block_kind="question")
    _item(store, run, n=3, block_kind="review")
    s = today.snapshot()
    assert s["counts"]["captcha"] == 1 and s["counts"]["question"] == 1
    assert s["counts"]["review"] == 1 and s["counts"]["total"] == 3


def test_every_job_card_carries_its_reasons(env):
    store, today, _ = env
    run = store.create_run_atomic({}, "dry")
    _item(store, run, n=1)
    card = today.snapshot()["best_jobs"][0]
    assert card["score"] == 70 and card["band"] == "possible fit"
    assert card["why"].startswith("70 possible fit")
    assert card["reasons"] == [{"label": "backend", "points": 8}]


# ---- the console ----

def test_console_answers_from_the_database(env):
    store, _, console = env
    run = store.create_run_atomic({}, "dry")
    _item(store, run, n=1, block_kind="captcha")
    assert "1" in console.ask("what is blocking")["answer"]
    assert console.ask("what should I do next")["answer"]
    assert "healthy" in console.ask("is everything working")["answer"].lower() or \
        console.ask("is everything working")["answer"].startswith(("WARN", "FAIL"))


def test_console_refuses_what_it_cannot_know(env):
    _, _, console = env
    for question in ["sing me a song", "will I get this job?", "what is the weather"]:
        r = console.ask(question)
        assert r.get("unknown") is True
        assert "do not have an answer" in r["answer"]


def test_console_explains_one_score(env):
    store, _, console = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, n=1)
    r = console.ask(f"why {iid}")
    assert "possible fit" in r["answer"] and "backend +8" in r["answer"]


def test_console_never_reports_sends_that_did_not_happen(env):
    store, _, console = env
    r = console.ask("why was nothing sent today")
    assert "Nothing sent today" in r["answer"]
    assert store.sent_today() == 0


def test_today_endpoint_serves_the_page_and_the_data(env, monkeypatch):
    monkeypatch.delenv("CVS_HOST", raising=False)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main, scheduler
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    monkeypatch.setattr(scheduler, "start", lambda: None)
    with TestClient(main.app) as c:
        assert c.get("/today").status_code == 200
        body = c.get("/api/today").json()
        assert set(body) >= {"goal", "next", "best_jobs", "counts", "health", "scheduler"}
        asked = c.post("/api/ask", json={"q": "what is blocking"}).json()
        assert asked["answer"]
        assert c.get("/api/ask/questions").json()["questions"]


def test_a_legacy_row_is_never_labelled_ready(env):
    """Rows staged before block_kind existed carry only a reason; the card must
    not claim they are ready to send."""
    store, today, _ = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, n=1, state="needs_input", block_kind=None,
                reason="CAPTCHA present")
    card = today.card(store.get_item(iid))
    assert card["block"] == "captcha" and card["state"] == "needs_input"
