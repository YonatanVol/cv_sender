"""Screening answers are the throughput lever: ~4 of 5 LinkedIn applications
stop on a question. Answer it once, every blocked posting retries."""
import json

import pytest

import cvsender.config as config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from cvsender.db.migrations import migrate
    migrate()
    monkeypatch.delenv("CVS_HOST", raising=False)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    monkeypatch.setattr(cloud, "push_answers", lambda *a, **k: True)
    with TestClient(main.app) as c:
        yield c


def _blocked(store, run, company, questions, key=None):
    iid = store.add_item(run, {
        "channel": "linkedin", "company": company, "title": "Engineer",
        "apply_url": "u", "dedupe_key": key or f"linkedin:{company}:1",
        "content_hash": key or company, "state": "needs_input"})
    store.transition_item(iid, ["needs_input"], "needs_input",
                          result_json=json.dumps({"questions": questions}))
    return iid


def test_gaps_group_by_question_and_rank_by_blocking(client):
    from cvsender.db import store
    run = store.create_run_atomic({}, "dry")
    yoe = {"label": "How many years of experience do you have with Python?", "kind": "text", "options": []}
    fulltime = {"label": "Are you available to work full-time?", "kind": "radio", "options": ["Yes", "No"]}
    _blocked(store, run, "a", [yoe, fulltime])
    _blocked(store, run, "b", [yoe])
    _blocked(store, run, "c", [yoe])
    gaps = client.get("/api/answers/gaps").json()
    assert gaps["blocked_items"] == 4
    assert gaps["gaps"][0]["label"] == yoe["label"] and gaps["gaps"][0]["blocking"] == 3
    assert gaps["gaps"][1]["options"] == ["Yes", "No"] and gaps["gaps"][1]["kind"] == "radio"


def test_answering_once_requeues_every_blocked_posting(client):
    from cvsender.db import store
    run = store.create_run_atomic({}, "dry")
    q = {"label": "What is your GPA?", "kind": "text", "options": []}
    ids = [_blocked(store, run, f"c{i}", [q], key=f"linkedin:c{i}:{i}") for i in range(3)]
    r = client.post("/api/answers/bulk", json={"answers": {q["label"]: "88"}}).json()
    assert r == {"ok": True, "learned": 1, "requeued": 3}
    assert all(store.get_item(i)["state"] == "queued" for i in ids)
    assert store.recall_answer("What is your GPA?") == "88"
    assert client.get("/api/answers/gaps").json()["gaps"] == []   # nothing left


def test_blank_answers_are_ignored(client):
    from cvsender.db import store
    run = store.create_run_atomic({}, "dry")
    q = {"label": "Notice period?", "kind": "text", "options": []}
    iid = _blocked(store, run, "a", [q])
    r = client.post("/api/answers/bulk", json={"answers": {q["label"]: "   "}}).json()
    assert r["learned"] == 0 and store.get_item(iid)["state"] == "needs_input"


def test_credentials_are_never_stored_from_this_page(client):
    from cvsender.db import store
    client.post("/api/answers/bulk", json={"answers": {"Password": "hunter2",
                                                       "תעודת זהות": "123456789"}})
    assert store.recall_answer("Password") is None
    assert store.recall_answer("תעודת זהות") is None


def test_answers_page_served(client):
    assert client.get("/answers").status_code == 200


# ---- question hygiene: only real questions reach the human ----

@pytest.mark.parametrize("raw,clean", [
    ("question_67972490 are you legally authorized to work in israel?",
     "Are you legally authorized to work in israel?"),
    ("country country*", "Country"),
    ("preferred_name preferred first name preferred first name*", "Preferred first name"),
    ("  How many years   with\nPython? ", "How many years with Python?"),
])
def test_clean_question(raw, clean):
    from cvsender.engine.answerbank import clean_question
    assert clean_question(raw) == clean


def test_worth_asking_filters_noise_credentials_and_known_answers():
    from cvsender.engine.answerbank import worth_asking
    profile = {"full_name": "Yonatan Volsky", "email": "y@x.com", "phone": "052",
               "work_authorized_il": 1}
    assert worth_asking("How many years of experience do you have with Go?", profile)
    assert worth_asking("What is your final GPA?", profile)
    assert not worth_asking("required field", profile)
    assert not worth_asking("Password", profile)                     # credential
    assert not worth_asking("תעודת זהות", profile)                    # national ID
    assert not worth_asking("353 voluntary self-identification of gender*", profile)
    assert not worth_asking("Are you legally authorized to work in Israel?", profile)
    assert not worth_asking("preferred_name preferred first name*", profile)  # from profile


def test_gaps_hide_noise(client):
    from cvsender.db import store
    store.save_profile({"full_name": "Y", "email": "y@x.com", "phone": "052"})
    run = store.create_run_atomic({}, "dry")
    _blocked(store, run, "a", [{"label": "required field", "kind": "text", "options": []},
                               {"label": "question_11 are you over 18?", "kind": "text", "options": []},
                               {"label": "What is your GPA?", "kind": "text", "options": []}])
    gaps = client.get("/api/answers/gaps").json()["gaps"]
    assert [g["label"] for g in gaps] == ["What is your GPA?"]


def test_first_and_last_name_come_from_the_full_name():
    from cvsender.engine.answerbank import profile_values
    v = profile_values({"full_name": "Yonatan Volsky"})
    assert v["first_name"] == "Yonatan" and v["last_name"] == "Volsky"
    v = profile_values({"full_name": "A B C", "first_name": "Ann"})
    assert v["first_name"] == "Ann" and v["last_name"] == "B C"
