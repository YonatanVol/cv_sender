"""Dead jobs must leave the queue.

41% of the queue was older than 30 days with nothing checking whether those
postings still existed; two sampled July ones redirected to an empty board.
A dead posting at the top of the queue wastes the only scarce resource here,
which is Yonatan's attention.
"""
import time

import pytest

import cvsender.config as config
from cvsender import freshness as f


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    return store


# ---- dates the boards already give us ----

@pytest.mark.parametrize("raw,expected_iso", [
    ("2026-09-01T10:00:00Z", "2026-09-01"),
    ("2026-09-01", "2026-09-01"),
    (1788307200, "2026-09-02"),          # seconds
    (1788307200000, "2026-09-02"),       # milliseconds (Lever)
])
def test_parse_posted(raw, expected_iso):
    ts = f.parse_posted(raw)
    assert time.strftime("%Y-%m-%d", time.gmtime(ts)) == expected_iso


@pytest.mark.parametrize("bad", [None, "", 0, "not a date", "yesterday-ish"])
def test_unparseable_dates_are_none_not_guesses(bad):
    assert f.parse_posted(bad) is None


@pytest.mark.parametrize("text,days", [
    ("3 days ago", 3), ("2 weeks ago", 14), ("1 month ago", 30),
    ("Just posted", 0), ("לפני 3 ימים", 3), ("לפני שבועיים", 14),
])
def test_linkedin_card_ages(text, days):
    now = 1_800_000_000.0
    got = f.relative_posted(text, now=now)
    assert got is not None
    assert round((now - got) / 86400) == days


# ---- is the posting still there ----

@pytest.mark.parametrize("code,url,body,expected", [
    (404, "u", "", f.CLOSED),
    (410, "u", "", f.CLOSED),
    (200, "https://x/jobs/12345", "we are no longer accepting applications", f.CLOSED),
    (200, "https://x/jobs/12345", "המשרה נסגרה", f.CLOSED),
    # redirected off the posting to a board root / error flag — the real case
    (200, "https://job-boards.greenhouse.io/anthropic?error=true", "", f.CLOSED),
    (200, "https://www.cloudflare.com/careers/jobs/", "", f.CLOSED),
    (200, "https://x/jobs/12345", "<form>apply</form>", f.ACTIVE),
    (500, "u", "", f.UNKNOWN),       # the board is broken, not the job
    (429, "u", "", f.UNKNOWN),
    (403, "u", "", f.UNKNOWN),
])
def test_classify(code, url, body, expected):
    assert f.classify(code, url, body, "https://x/jobs/12345") == expected


def test_a_redirect_that_keeps_the_job_id_is_never_dismissed():
    """Some boards forward to the company's own site carrying the posting id.
    That is not evidence the job is gone, so it must never be dismissed."""
    assert f.classify(200, "https://careers.acme.com/apply/12345-backend", "",
                      "https://x/jobs/12345") != f.CLOSED


def test_a_redirect_somewhere_unrecognised_is_unknown_not_closed():
    assert f.classify(200, "https://acme.com/talent-network", "",
                      "https://x/jobs/12345") == f.UNKNOWN


# ---- when to check ----

def test_needs_check_only_for_old_unverified_items():
    now = time.time()
    fresh = {"last_seen_at": now - 2 * 86400, "checked_at": 0, "liveness": "active"}
    old = {"last_seen_at": now - 40 * 86400, "checked_at": 0, "liveness": "unknown"}
    just_checked = {"last_seen_at": now - 40 * 86400, "checked_at": now - 3600,
                    "liveness": "active"}
    settled = {"last_seen_at": now - 40 * 86400, "checked_at": 0, "liveness": "closed"}
    assert f.needs_check(fresh, now) is False
    assert f.needs_check(old, now) is True
    assert f.needs_check(just_checked, now) is False
    assert f.needs_check(settled, now) is False


# ---- the queue ----

def _item(store, run, key, state="needs_input"):
    return store.add_item(run, {"channel": "greenhouse", "company": "acme",
                                "title": "Backend Engineer", "apply_url": "https://x/jobs/1",
                                "dedupe_key": key, "content_hash": key, "state": state})


def test_a_closed_posting_leaves_the_queue_but_stays_in_history(env, monkeypatch):
    store = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, "greenhouse:acme:1")
    assert len(store.assist_queue(50)) == 1
    monkeypatch.setattr(f, "check_url", lambda url, client=None: f.CLOSED)
    assert f.verify_item(store.get_item(iid)) == f.CLOSED
    assert store.assist_queue(50) == []                      # gone from the queue
    assert store.get_item(iid)["state"] == "skipped"          # still in history
    assert store.get_item(iid)["liveness"] == "closed"
    assert store.is_dismissed("greenhouse:acme:1") is True


def test_an_active_posting_is_kept_and_stamped(env, monkeypatch):
    store = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, "greenhouse:acme:2")
    monkeypatch.setattr(f, "check_url", lambda url, client=None: f.ACTIVE)
    assert f.verify_item(store.get_item(iid)) == f.ACTIVE
    item = store.get_item(iid)
    assert item["liveness"] == "active" and item["checked_at"] > 0
    assert len(store.assist_queue(50)) == 1


def test_an_unknown_verdict_changes_nothing(env, monkeypatch):
    """A 500 or a rate limit must never dismiss a job."""
    store = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, "greenhouse:acme:3")
    monkeypatch.setattr(f, "check_url", lambda url, client=None: f.UNKNOWN)
    f.verify_item(store.get_item(iid))
    assert store.get_item(iid)["state"] == "needs_input"
    assert len(store.assist_queue(50)) == 1


def test_seeing_a_posting_again_refreshes_it(env):
    store = env
    run = store.create_run_atomic({}, "dry")
    iid = _item(store, run, "greenhouse:acme:4")
    store.touch_seen("greenhouse:acme:4", posted_at=1_700_000_000.0)
    item = store.get_item(iid)
    assert item["last_seen_at"] > 0 and item["liveness"] == "active"
    assert item["posted_at"] == 1_700_000_000.0


# ---- a live job must never be dismissed on a loose word match ----

@pytest.mark.parametrize("body", [
    "Join 500 companies using our platform",      # 'nie' inside 'companies'
    "Access Denied to some resources",            # 'nie' inside 'Denied'
    "convenience, beanie, brownies",
    "We are accepting applications now",
    "This position is open and closed-loop control is a plus",
])
def test_ordinary_words_never_close_a_job(body):
    assert f.classify(200, "https://x/jobs/12345", body,
                      "https://x/jobs/12345") == f.ACTIVE


@pytest.mark.parametrize("body", [
    "We are no longer accepting applications for this role",
    "This job is closed",
    "המשרה נסגרה",
])
def test_real_closure_phrases_still_close(body):
    assert f.classify(200, "https://x/jobs/12345", body,
                      "https://x/jobs/12345") == f.CLOSED
