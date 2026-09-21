"""One real position, one card.

dedupe_key is channel-prefixed, so the same job listed on LinkedIn and on the
company's Greenhouse board was structurally two rows and two cards.
"""
import pytest

import cvsender.config as config
from cvsender.channels.base import job_identity


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store as s
    migrate()
    return s


@pytest.mark.parametrize("a,b", [
    (("Comigo.io", "Junior Systems Implementer", "Petah Tikva, Center District, Israel"),
     ("comigo", "junior systems implementer", "Petah Tikva")),
    (("Acme Technologies Ltd", "Backend Engineer", "Tel Aviv, Israel"),
     ("Acme", "Backend Engineer - Remote", "Tel Aviv")),
    (("Wiz", "Software Engineer (m/f/d)", "Tel Aviv"),
     ("wiz.io", "Software Engineer", "Tel Aviv")),
    (("Gong", "Full Stack Engineer, Full-Time", "Ramat Gan"),
     ("Gong Labs", "Full Stack Engineer", "Ramat Gan")),
])
def test_the_same_position_has_one_identity(a, b):
    assert job_identity(*a) == job_identity(*b)


@pytest.mark.parametrize("a,b", [
    (("Acme", "Backend Engineer", "Tel Aviv"), ("Acme", "Frontend Engineer", "Tel Aviv")),
    (("Acme", "Backend Engineer", "Tel Aviv"), ("Other", "Backend Engineer", "Tel Aviv")),
    (("Acme", "Backend Engineer", "Tel Aviv"), ("Acme", "Backend Engineer", "Haifa")),
])
def test_different_positions_stay_different(a, b):
    assert job_identity(*a) != job_identity(*b)


def _add(store, run, channel, key, title="Backend Engineer", company="Acme"):
    ident = job_identity(company, title, "Tel Aviv")
    return store.add_item(run, {"channel": channel, "company": company, "title": title,
                                "location": "Tel Aviv", "apply_url": f"https://{channel}/x",
                                "dedupe_key": key, "content_hash": key,
                                "identity": ident, "state": "needs_input"})


def test_one_job_on_two_boards_is_one_card(store):
    run = store.create_run_atomic({}, "dry")
    _add(store, run, "linkedin", "linkedin:acme:111")
    _add(store, run, "greenhouse", "greenhouse:acme:222")
    queue = store.assist_queue(50)
    assert len(queue) == 1, [q["channel"] for q in queue]


def test_a_position_already_queued_is_not_staged_again(store):
    run = store.create_run_atomic({}, "dry")
    _add(store, run, "linkedin", "linkedin:acme:111")
    assert store.identity_in_queue(job_identity("Acme", "Backend Engineer", "Tel Aviv")) is True
    assert store.identity_in_queue(job_identity("Acme", "Data Engineer", "Tel Aviv")) is False


def test_a_closed_position_does_not_block_a_repost(store):
    run = store.create_run_atomic({}, "dry")
    iid = _add(store, run, "linkedin", "linkedin:acme:111")
    store.set_liveness(iid, "closed")
    assert store.identity_in_queue(job_identity("Acme", "Backend Engineer", "Tel Aviv")) is False


def test_backfill_gives_old_rows_an_identity(store):
    run = store.create_run_atomic({}, "dry")
    iid = store.add_item(run, {"channel": "linkedin", "company": "Acme", "title": "Backend Engineer",
                               "location": "Tel Aviv", "apply_url": "u",
                               "dedupe_key": "linkedin:acme:9", "content_hash": "h",
                               "state": "needs_input"})
    assert store.get_item(iid)["identity"] is None
    assert store.backfill_identities() == 1
    assert store.get_item(iid)["identity"] == job_identity("Acme", "Backend Engineer", "Tel Aviv")


def test_add_item_persists_identity_and_freshness(store):
    """Regression: add_item had a fixed column list and silently dropped both,
    so duplicate collapse and freshness had nothing to work with."""
    run = store.create_run_atomic({}, "dry")
    iid = store.add_item(run, {"channel": "linkedin", "company": "Acme", "title": "Backend",
                               "apply_url": "u", "dedupe_key": "linkedin:acme:1",
                               "content_hash": "h", "identity": "acme|backend|tel-aviv",
                               "posted_at": 1_700_000_000.0, "liveness": "active",
                               "state": "needs_input"})
    row = store.get_item(iid)
    assert row["identity"] == "acme|backend|tel-aviv"
    assert row["posted_at"] == 1_700_000_000.0
    assert row["liveness"] == "active"
    assert row["first_seen_at"] and row["last_seen_at"]
