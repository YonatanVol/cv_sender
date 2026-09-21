"""Typed data-access for v2. Every write is short and one-shot; the run/item
state machine and dedupe invariants live here so callers can't violate them.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional, Sequence

from .connection import connect, ro, tx

# A run that is *working* — the single-run lock. 'awaiting_confirm' is NOT
# here: that run is parked for a human, its items are durable, and treating it
# as active blocked every later run (the morning staging would never start
# until someone opened the dashboard and cancelled it).
ACTIVE_STATUSES = ("running", "sending")
PARKED_STATUSES = ("awaiting_confirm",)


def _now() -> float:
    return time.time()


def _row(r) -> Optional[dict]:
    return dict(r) if r is not None else None


# ------------------------------- profile -----------------------------------

PROFILE_FIELDS = [
    "full_name", "first_name", "last_name", "email", "phone", "location",
    "region", "linkedin", "github", "portfolio", "needs_sponsorship",
    "work_authorized_il", "cv_path", "cv_sha256", "cv_name", "cv_size",
    "cv_pages", "extra_answers_json",
]


def get_profile() -> Optional[dict]:
    with ro() as c:
        return _row(c.execute("SELECT * FROM profile WHERE id=1").fetchone())


def save_profile(data: dict) -> None:
    vals = {k: data.get(k) for k in PROFILE_FIELDS if k in data}
    if vals.get("full_name") and not vals.get("first_name"):
        parts = vals["full_name"].split()
        vals["first_name"] = parts[0] if parts else ""
        vals["last_name"] = " ".join(parts[1:])
    vals["updated_at"] = _now()
    cols = ", ".join(vals)
    ph = ", ".join(":" + k for k in vals)
    upd = ", ".join(f"{k}=excluded.{k}" for k in vals)
    with tx() as c:
        c.execute(
            f"INSERT INTO profile (id, {cols}) VALUES (1, {ph}) "
            f"ON CONFLICT(id) DO UPDATE SET {upd}",
            vals,
        )


# -------------------------------- runs -------------------------------------

def create_run_atomic(options: dict, mode: str) -> Optional[int]:
    """Insert a run only if none is active. Returns run_id, or None on conflict."""
    now = _now()
    with tx() as c:
        cur = c.execute(
            "INSERT INTO runs (options_json, mode, phase, status, worker_pid, "
            "heartbeat_at, started_at) "
            "SELECT ?, ?, 'prepare', 'running', ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM runs WHERE status IN "
            "('running','sending'))",
            (json.dumps(options), mode, os.getpid(), now, now),
        )
        return cur.lastrowid if cur.rowcount == 1 else None


def get_run(run_id: int) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def get_active_run() -> Optional[dict]:
    """The run currently working. A parked 'awaiting_confirm' run is not one:
    see ACTIVE_STATUSES."""
    with ro() as c:
        return _row(c.execute(
            "SELECT * FROM runs WHERE status IN ('running','sending') "
            "ORDER BY id DESC LIMIT 1").fetchone())


def parked_run() -> Optional[dict]:
    """The newest run waiting on a human confirm, if any."""
    with ro() as c:
        return _row(c.execute(
            "SELECT * FROM runs WHERE status='awaiting_confirm' "
            "ORDER BY id DESC LIMIT 1").fetchone())


def list_runs(limit: int = 50) -> list[dict]:
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def update_run(run_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE runs SET {sets} WHERE id=?",
                  (*fields.values(), run_id))


def heartbeat(run_id: int) -> None:
    with tx() as c:
        c.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (_now(), run_id))


def request_cancel(run_id: int) -> None:
    with tx() as c:
        c.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))


def is_cancel_requested(run_id: int) -> bool:
    with ro() as c:
        r = c.execute("SELECT cancel_requested FROM runs WHERE id=?",
                      (run_id,)).fetchone()
        return bool(r and r[0])


# ------------------------------ run_items ----------------------------------

def add_item(run_id: int, item: dict) -> Optional[int]:
    """Insert a candidate. Returns item_id, or None if it collides with an
    existing (run_id, dedupe_key) (already queued this run)."""
    now = _now()
    payload = {
        "run_id": run_id,
        "channel": item["channel"],
        "company": item.get("company"),
        "title": item.get("title"),
        "location": item.get("location"),
        "url": item.get("url"),
        "apply_url": item.get("apply_url"),
        "dedupe_key": item["dedupe_key"],
        "content_hash": item.get("content_hash"),
        "score": item.get("score"),
        "score_json": json.dumps(item.get("score_json", {})),
        "state": item.get("state", "queued"),
        "reason": item.get("reason"),
        "created_at": now,
        "updated_at": now,
        # Freshness and identity travel with the job from discovery. They were
        # silently dropped while this payload had a fixed column list.
        "identity": item.get("identity"),
        "posted_at": item.get("posted_at"),
        "first_seen_at": item.get("first_seen_at", now),
        "last_seen_at": item.get("last_seen_at", now),
        "liveness": item.get("liveness", "unknown"),
        "block_kind": item.get("block_kind"),
    }
    cols = ", ".join(payload)
    ph = ", ".join("?" for _ in payload)
    with tx() as c:
        cur = c.execute(
            f"INSERT OR IGNORE INTO run_items ({cols}) VALUES ({ph})",
            tuple(payload.values()),
        )
        return cur.lastrowid if cur.rowcount == 1 else None


def get_item(item_id: int) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute("SELECT * FROM run_items WHERE id=?",
                              (item_id,)).fetchone())


def list_items(run_id: int, states: Optional[Sequence[str]] = None) -> list[dict]:
    with ro() as c:
        if states:
            q = ",".join("?" for _ in states)
            rows = c.execute(
                f"SELECT * FROM run_items WHERE run_id=? AND state IN ({q}) "
                "ORDER BY id", (run_id, *states)).fetchall()
        else:
            rows = c.execute("SELECT * FROM run_items WHERE run_id=? ORDER BY id",
                             (run_id,)).fetchall()
        return [dict(r) for r in rows]


def next_queued(run_id: int) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute(
            "SELECT * FROM run_items WHERE run_id=? AND state='queued' "
            "ORDER BY score DESC NULLS LAST, id LIMIT 1", (run_id,)).fetchone())


def next_in_state(run_id: int, state: str) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute(
            "SELECT * FROM run_items WHERE run_id=? AND state=? ORDER BY id LIMIT 1",
            (run_id, state)).fetchone())


def set_item(item_id: int, **fields) -> None:
    if not fields:
        return
    # Touch updated_at unless the caller set it explicitly (tests/backfills).
    fields.setdefault("updated_at", _now())
    sets = ", ".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE run_items SET {sets} WHERE id=?",
                  (*fields.values(), item_id))


def transition_item(item_id: int, from_states: Sequence[str], to_state: str,
                    **fields) -> bool:
    """Guarded transition: only moves the item if it is currently in one of
    from_states. Returns True if it changed (the two-tab / double-click guard)."""
    fields["state"] = to_state
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in fields)
    q = ",".join("?" for _ in from_states)
    with tx() as c:
        cur = c.execute(
            f"UPDATE run_items SET {sets} WHERE id=? AND state IN ({q})",
            (*fields.values(), item_id, *from_states),
        )
        return cur.rowcount == 1


def item_counts(run_id: int) -> dict:
    with ro() as c:
        rows = c.execute(
            "SELECT state, COUNT(*) n FROM run_items WHERE run_id=? GROUP BY state",
            (run_id,)).fetchall()
        return {r["state"]: r["n"] for r in rows}


# ------------------------------- events ------------------------------------

def add_event(run_id: int, type: str, message: str = "",
              item_id: Optional[int] = None, level: str = "info",
              data: Optional[dict] = None) -> int:
    with tx() as c:
        cur = c.execute(
            "INSERT INTO run_events (run_id, item_id, at, level, type, message, "
            "data_json) VALUES (?,?,?,?,?,?,?)",
            (run_id, item_id, _now(), level, type, message,
             json.dumps(data or {})),
        )
        return cur.lastrowid


def events_after(run_id: int, cursor: int, limit: int = 200) -> list[dict]:
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id LIMIT ?",
            (run_id, cursor, limit)).fetchall()]


# ---------------------------- applications ---------------------------------

CONTENT_BLOCK_DAYS = 60          # content-only matches expire; identity never does


def canonical_url(url: Optional[str]) -> str:
    """Strip tracking params/fragments so the same posting matches itself."""
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit
        p = urlsplit(url.strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").rstrip("/")
        return urlunsplit((p.scheme.lower() or "https", host, path, "", ""))
    except Exception:
        return (url or "").strip().lower()


def dismiss(item: dict, kind: str = "unavailable",
            note: str = "", content_block_days: int = CONTENT_BLOCK_DAYS) -> None:
    """Stop offering this job.

    Tiered on purpose (a closed role can be reposted later with identical text):
      * same channel + external id  -> permanent
      * same canonical URL          -> permanent
      * same content_hash only      -> TEMPORARY (expires), so a genuine repost
                                       under a new id resurfaces
    Never written to `applications`: it was not sent, so it must not inflate the
    sent count. Keeps dismissed_at, reason and source details for auditing.
    """
    key = item["dedupe_key"]
    channel = item.get("channel") or (key.split(":", 1)[0] if ":" in key else "")
    external_id = key.rsplit(":", 1)[-1] if ":" in key else ""
    url = item.get("apply_url") or item.get("url") or ""
    now = _now()
    expires = now + max(0, content_block_days) * 86400 if item.get("content_hash") \
        else None
    with tx() as c:
        c.execute(
            "INSERT INTO dismissed (dedupe_key, content_hash, kind, company, "
            "title, at, apply_url, canonical_url, channel, external_id, note, "
            "content_expires_at, restored_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL) "
            "ON CONFLICT(dedupe_key) DO UPDATE SET kind=excluded.kind, "
            "at=excluded.at, note=excluded.note, "
            "content_expires_at=excluded.content_expires_at, restored_at=NULL",
            (key, item.get("content_hash"), kind, item.get("company"),
             item.get("title"), now, url, canonical_url(url), channel,
             external_id, note, expires))


def restore_dismissed(dedupe_key: str) -> bool:
    """Undo a dismissal so the job can be offered again."""
    with tx() as c:
        cur = c.execute("DELETE FROM dismissed WHERE dedupe_key=?", (dedupe_key,))
        return cur.rowcount > 0


def is_dismissed(dedupe_key: str, content_hash: Optional[str] = None,
                 url: Optional[str] = None) -> bool:
    now = _now()
    with ro() as c:
        # 1) exact posting identity (channel:company:external_id) -> permanent
        if c.execute("SELECT 1 FROM dismissed WHERE dedupe_key=? "
                     "AND restored_at IS NULL", (dedupe_key,)).fetchone():
            return True
        # 2) same canonical URL -> permanent
        canon = canonical_url(url)
        if canon and c.execute(
                "SELECT 1 FROM dismissed WHERE canonical_url=? AND canonical_url<>'' "
                "AND restored_at IS NULL", (canon,)).fetchone():
            return True
        # 3) identical text only -> temporary, so a real repost comes back
        if content_hash and c.execute(
                "SELECT 1 FROM dismissed WHERE content_hash=? AND restored_at IS NULL "
                "AND (content_expires_at IS NULL OR content_expires_at > ?)",
                (content_hash, now)).fetchone():
            return True
        return False


def list_dismissed(limit: int = 300) -> list[dict]:
    """For the 'dismissed jobs' screen, newest first, with why + when."""
    now = _now()
    with ro() as c:
        rows = c.execute(
            "SELECT * FROM dismissed WHERE restored_at IS NULL "
            "ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            exp = d.get("content_expires_at")
            d["content_block_active"] = bool(exp and exp > now)
            d["content_expires_in_days"] = (
                int((exp - now) // 86400) if exp and exp > now else 0)
            out.append(d)
        return out


def dismissed_count() -> int:
    with ro() as c:
        return c.execute("SELECT COUNT(*) n FROM dismissed "
                         "WHERE restored_at IS NULL").fetchone()["n"]


def already_handled(dedupe_key: str, content_hash: Optional[str] = None,
                    url: Optional[str] = None) -> bool:
    """Skip this job in future runs: either genuinely sent, or dismissed."""
    return already_sent(dedupe_key, content_hash) or \
        is_dismissed(dedupe_key, content_hash, url)


def backfill_identities() -> int:
    """Give existing rows their identity once, so old duplicates collapse too."""
    from ..channels.base import job_identity
    n = 0
    with ro() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, company, title, location FROM run_items WHERE identity IS NULL")]
    with tx() as c:
        for r in rows:
            c.execute("UPDATE run_items SET identity=? WHERE id=?",
                      (job_identity(r["company"] or "", r["title"] or "",
                                    r["location"] or ""), r["id"]))
            n += 1
    return n


def identity_in_queue(identity: str, within_s: float = 7 * 86400) -> bool:
    """Is this real position already waiting, from any board?"""
    if not identity:
        return False
    with ro() as c:
        return c.execute(
            "SELECT 1 FROM run_items WHERE identity=? AND state IN "
            "('needs_input','ready','failed') AND COALESCE(liveness,'unknown') != 'closed' "
            "AND updated_at >= ? LIMIT 1",
            (identity, _now() - within_s)).fetchone() is not None


def waiting_in_queue(dedupe_key: str, within_s: float = 7 * 86400) -> bool:
    """True when this posting was prepared recently and is still parked for a
    human (needs_input / ready / failed). Re-preparing it would only repeat the
    same blocker and, on LinkedIn, spend page views for nothing."""
    with ro() as c:
        return c.execute(
            "SELECT 1 FROM run_items WHERE dedupe_key=? AND state IN "
            "('needs_input','ready','failed') AND updated_at >= ? LIMIT 1",
            (dedupe_key, _now() - within_s)).fetchone() is not None


def already_sent(dedupe_key: str, content_hash: Optional[str] = None) -> bool:
    """Terminal dedupe: only a verified 'sent' application blocks re-offering."""
    with ro() as c:
        if c.execute("SELECT 1 FROM applications WHERE dedupe_key=?",
                     (dedupe_key,)).fetchone():
            return True
        if content_hash and c.execute(
                "SELECT 1 FROM applications WHERE content_hash=?",
                (content_hash,)).fetchone():
            return True
        return False


# ------------------------------ freshness ----------------------------------

def set_liveness(item_id: int, liveness: str) -> None:
    """Record what a liveness probe found, and when."""
    with tx() as c:
        c.execute("UPDATE run_items SET liveness=?, checked_at=? WHERE id=?",
                  (liveness, _now(), item_id))


def touch_seen(dedupe_key: str, posted_at: Optional[float] = None) -> None:
    """This posting was seen again in discovery: it is still listed."""
    now = _now()
    with tx() as c:
        c.execute("UPDATE run_items SET last_seen_at=?, liveness='active', "
                  "posted_at=COALESCE(posted_at, ?) WHERE dedupe_key=?",
                  (now, posted_at, dedupe_key))


def queue_age_report() -> dict:
    """Queue composition by age and liveness — the number that made freshness
    a priority (41% of the queue was older than 30 days)."""
    now = _now()
    out = {"total": 0, "fresh_7d": 0, "stale_14d": 0, "old_30d": 0,
           "closed": 0, "unverified_old": 0}
    for i in assist_queue(limit=2000):
        out["total"] += 1
        seen = i.get("last_seen_at") or i.get("updated_at") or 0
        age_d = (now - seen) / 86400
        if age_d <= 7:
            out["fresh_7d"] += 1
        elif age_d <= 30:
            out["stale_14d"] += 1
        else:
            out["old_30d"] += 1
        if (i.get("liveness") or "") == "closed":
            out["closed"] += 1
        if age_d > 14 and not i.get("checked_at"):
            out["unverified_old"] += 1
    return out


# ----------------------------- CV variants ---------------------------------

def upsert_cv_variant(name: str, label: str, path: str, sha256: str,
                      tags: list[str], pages: Optional[int] = None,
                      is_default: bool = False) -> None:
    with tx() as c:
        if is_default:
            c.execute("UPDATE cv_variants SET is_default=0")
        c.execute(
            "INSERT INTO cv_variants (name, label, path, sha256, tags_json, "
            "pages, is_default, created_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET label=excluded.label, "
            "path=excluded.path, sha256=excluded.sha256, "
            "tags_json=excluded.tags_json, pages=excluded.pages, "
            "is_default=excluded.is_default",
            (name, label, path, sha256, json.dumps(tags), pages,
             1 if is_default else 0, _now()))


def list_cv_variants() -> list[dict]:
    with ro() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM cv_variants ORDER BY is_default DESC, name")]
    for r in rows:
        try:
            r["tags"] = json.loads(r.get("tags_json") or "[]")
        except ValueError:
            r["tags"] = []
    return rows


def delete_cv_variant(name: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM cv_variants WHERE name=?", (name,))


# ------------------------------ sessions -----------------------------------

def create_session(token_hash: str, ttl_s: float) -> None:
    now = _now()
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO sessions (token_hash, created_at, "
                  "expires_at, last_seen) VALUES (?,?,?,?)",
                  (token_hash, now, now + ttl_s, now))


def touch_session(token_hash: str, ttl_s: float) -> bool:
    """Validate and slide the expiry. False when unknown or expired.

    Whether the session is valid is decided by a READ, which never waits for the
    run that is busy writing. Sliding the expiry and reaping a dead session are
    housekeeping: if the database is locked at that moment they are skipped, so
    a busy run can no longer turn a signed-in page load into a 500.
    """
    now = _now()
    with ro() as c:
        row = c.execute("SELECT expires_at FROM sessions WHERE token_hash=?",
                        (token_hash,)).fetchone()
    if row is None:
        return False
    if row["expires_at"] < now:
        try:
            with tx() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        except sqlite3.OperationalError:
            pass
        return False
    try:
        with tx() as c:
            c.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
                      (now, now + ttl_s, token_hash))
    except sqlite3.OperationalError:
        pass                       # the expiry slides on the next request
    return True


def delete_session(token_hash: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


def delete_all_sessions() -> int:
    with tx() as c:
        return c.execute("DELETE FROM sessions").rowcount


def purge_expired_sessions() -> int:
    with tx() as c:
        return c.execute("DELETE FROM sessions WHERE expires_at < ?",
                         (_now(),)).rowcount


# ---------------------------- settings -------------------------------------

def get_setting(key: str) -> Optional[str]:
    with ro() as c:
        r = c.execute("SELECT value FROM app_settings WHERE key=?",
                      (key,)).fetchone()
        return r["value"] if r else None


def set_setting(key: str, value: Optional[str]) -> None:
    with tx() as c:
        if value is None:
            c.execute("DELETE FROM app_settings WHERE key=?", (key,))
        else:
            c.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at", (key, value, _now()))


# --------------------------- answer bank -----------------------------------

def normalize_question(q: str) -> str:
    """Stable key for a screening question: lowercase, collapse whitespace and
    punctuation so trivial wording/format differences still hit the same entry."""
    import re
    s = (q or "").strip().lower()
    s = re.sub(r"[\*‎‏]", "", s)
    s = re.sub(r"[^\w\s֐-׿]+", " ", s)   # keep Hebrew letters
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]


def learn_answer(question: str, answer: str, kind: str = "text") -> None:
    """Remember one screening answer so it is auto-filled forever after.

    Refuses to store credentials / government IDs / financial details even if
    they are submitted — those must never be persisted or replayed into a form.
    """
    from ..engine.answerbank import is_prohibited
    if is_prohibited(question):
        return
    qkey = normalize_question(question)
    if not qkey or answer is None or answer == "":
        return
    now = _now()
    with tx() as c:
        c.execute(
            "INSERT INTO answer_bank (qkey, question, answer, kind, uses, "
            "created_at, updated_at) VALUES (?,?,?,?,0,?,?) "
            "ON CONFLICT(qkey) DO UPDATE SET answer=excluded.answer, "
            "kind=excluded.kind, updated_at=excluded.updated_at",
            (qkey, question, answer, kind, now, now))


def recall_answer(question: str) -> Optional[str]:
    qkey = normalize_question(question)
    if not qkey:
        return None
    with ro() as c:
        r = c.execute("SELECT answer FROM answer_bank WHERE qkey=?",
                      (qkey,)).fetchone()
        return r["answer"] if r else None


def bump_answer_use(question: str) -> None:
    with tx() as c:
        c.execute("UPDATE answer_bank SET uses=uses+1 WHERE qkey=?",
                  (normalize_question(question),))


def list_answers() -> list[dict]:
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM answer_bank ORDER BY uses DESC, updated_at DESC")]


def answer_gaps(limit: int = 60) -> list[dict]:
    """Questions blocking the queue right now, most-blocking first.

    One row per distinct question (normalised), with how many postings it
    blocks and an example. Answering it once unblocks all of them, which is the
    single biggest lever on how many applications can finish.
    """
    from ..engine import answerbank as ab
    profile = get_profile() or {}
    gaps: dict[str, dict] = {}
    with ro() as c:
        rows = c.execute(
            "SELECT id, company, title, result_json FROM run_items "
            "WHERE state IN ('needs_input','failed') AND result_json IS NOT NULL "
            "AND id NOT IN (SELECT item_id FROM applications WHERE item_id IS NOT NULL) "
            "ORDER BY updated_at DESC LIMIT 2000").fetchall()
    for r in rows:
        try:
            questions = (json.loads(r["result_json"]) or {}).get("questions") or []
        except (TypeError, ValueError):
            continue
        for q in questions:
            raw = (q or {}).get("label") if isinstance(q, dict) else None
            if not raw:
                continue
            label = ab.clean_question(raw)
            if not ab.worth_asking(label, profile):
                continue                      # noise, credential, or self-answerable
            qkey = normalize_question(label)
            if not qkey or recall_answer(label):
                continue                      # already answered once
            g = gaps.setdefault(qkey, {"qkey": qkey, "label": label,
                                       "kind": (q.get("kind") or "text"),
                                       "options": q.get("options") or [],
                                       "blocking": 0, "item_ids": [],
                                       "example": f"{r['company']} — {r['title']}"})
            g["blocking"] += 1
            if len(g["item_ids"]) < 50:
                g["item_ids"].append(r["id"])
            if not g["options"] and q.get("options"):
                g["options"] = q["options"]
    out = sorted(gaps.values(), key=lambda g: -g["blocking"])
    return out[:limit]


def requeue_items(item_ids: list[int], reason: str) -> int:
    """Send items back to the queue so the next run retries them."""
    n = 0
    for iid in item_ids:
        n += 1 if transition_item(iid, ["needs_input", "failed"], "queued",
                                  reason=reason) else 0
    return n


# --------------------------- daily counters --------------------------------

def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def bump_daily(channel: str) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO daily_counts (day, channel, sent) VALUES (?,?,1) "
            "ON CONFLICT(day, channel) DO UPDATE SET sent = sent + 1",
            (_today(), channel))


def _local_midnight() -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def sent_today(channel: Optional[str] = None) -> int:
    """Applications actually sent since local midnight.

    Reads the applications table, the one record every verified or
    user-confirmed send writes. The old daily_counts table was only bumped by
    'I sent it', so automatic LinkedIn sends never showed up in the badge.
    """
    q = "SELECT COUNT(*) n FROM applications WHERE sent_at >= ?"
    args: list = [_local_midnight()]
    if channel:
        q += " AND channel = ?"
        args.append(channel)
    with ro() as c:
        return c.execute(q, args).fetchone()["n"]


# --------------------------- assist queue ----------------------------------

def assist_queue(limit: int = 200) -> list[dict]:
    """Everything a human could finish right now: filled-but-blocked items,
    newest first, excluding anything already sent (dedupe by key)."""
    with ro() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT i.* FROM run_items i "
            "WHERE i.state IN ('needs_input','failed','ready') "
            "AND COALESCE(i.liveness,'unknown') != 'closed' "
            "  AND NOT EXISTS (SELECT 1 FROM applications a "
            "                  WHERE a.dedupe_key = i.dedupe_key) "
            "  AND NOT EXISTS (SELECT 1 FROM dismissed d "
            "                  WHERE d.dedupe_key = i.dedupe_key) "
            "GROUP BY i.dedupe_key "
            "ORDER BY (i.state='ready') DESC, i.score DESC, i.id DESC LIMIT ?",
            (limit,)).fetchall()]
    # One real position, one card: the same job listed on LinkedIn and on a
    # company board has two dedupe_keys but one identity. Collapsed here rather
    # than in SQL so rows of the same key with slightly different titles (a
    # scraped vs. an API title) still count as one.
    seen, out = set(), []
    for r in rows:
        key = r.get("identity") or r.get("dedupe_key")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def blocked_companies(min_hits: int = 1) -> set[str]:
    """Companies whose forms have blocked us before (CAPTCHA / no usable form).

    Used to order preparation so boards that actually yield sendable
    applications go first — a run's effort is finite, and an item that will
    certainly need a human is worth less than one that can auto-send.
    """
    with ro() as c:
        rows = c.execute(
            "SELECT company, COUNT(*) n FROM run_items "
            "WHERE state IN ('needs_input','failed') AND ("
            "  reason LIKE '%CAPTCHA%' OR reason LIKE '%no recognized form%' "
            "  OR reason LIKE '%account%') "
            "GROUP BY company HAVING n >= ?", (min_hits,)).fetchall()
        return {r["company"] for r in rows if r["company"]}


def mark_assist(item_id: int) -> None:
    with tx() as c:
        c.execute("UPDATE run_items SET assist_at=? WHERE id=?", (_now(), item_id))


def record_application(item: dict, evidence: str, cv_variant: str = "",
                       cv_sha256: str = "") -> int:
    """Idempotent terminal write — only call with real confirmation evidence.

    The CV variant is recorded so reply rates can later be compared per CV.
    """
    now = _now()
    with tx() as c:
        cur = c.execute(
            "INSERT INTO applications (dedupe_key, content_hash, channel, company, "
            "title, apply_url, status, confirmation_evidence, run_id, item_id, "
            "sent_at, stage, stage_at, cv_variant, cv_sha256) "
            "VALUES (?,?,?,?,?,?, 'sent', ?,?,?,?, 'applied', ?,?,?) "
            "ON CONFLICT(dedupe_key) DO NOTHING",
            (item["dedupe_key"], item.get("content_hash"), item["channel"],
             item.get("company"), item.get("title"), item.get("apply_url"),
             evidence, item.get("run_id"), item["id"], now, now,
             cv_variant or None, cv_sha256 or None),
        )
        return cur.lastrowid


def recent_applications(limit: int = 20) -> list[dict]:
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM applications ORDER BY sent_at DESC LIMIT ?", (limit,))]


def move_items_to_run(run_id: int, item_ids: list[int],
                      states: tuple = ("ready",)) -> int:
    """Move prepared items into another run.

    The scheduler stages in DRY mode, and a confirm is only allowed on a LIVE
    run, so work prepared by the morning search could never be sent without
    this: the items are moved into a live run, keeping their filled form,
    screenshot and SendHandle.
    """
    if not item_ids:
        return 0
    marks = ",".join("?" for _ in item_ids)
    smarks = ",".join("?" for _ in states)
    with tx() as c:
        cur = c.execute(
            f"UPDATE run_items SET run_id=?, updated_at=? WHERE id IN ({marks}) "
            f"AND state IN ({smarks})",
            (run_id, _now(), *item_ids, *states))
        return cur.rowcount


# ------------------------------ tracker ------------------------------------
# What happened after the send. 'applied' is where every application starts;
# the rest are only ever set by Yonatan, because only he sees the replies.
STAGES = ("applied", "replied", "screen", "interview", "offer",
          "rejected", "withdrawn", "closed")
OPEN_STAGES = ("applied", "replied", "screen", "interview", "offer")
FOLLOWUP_AFTER_DAYS = 7


def list_applications(stage: Optional[str] = None, limit: int = 500) -> list[dict]:
    q = "SELECT * FROM applications"
    args: list = []
    if stage:
        q += " WHERE stage = ?"
        args.append(stage)
    q += " ORDER BY sent_at DESC LIMIT ?"
    args.append(limit)
    with ro() as c:
        return [dict(r) for r in c.execute(q, args)]


def get_application(app_id: int) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute("SELECT * FROM applications WHERE id=?",
                              (app_id,)).fetchone())


def set_stage(app_id: int, stage: str, note: str = "") -> bool:
    """Move an application along, and keep the history. Unknown stage: no-op."""
    if stage not in STAGES:
        return False
    now = _now()
    with tx() as c:
        cur = c.execute("UPDATE applications SET stage=?, stage_at=?, "
                        "note=COALESCE(NULLIF(?,''), note) WHERE id=?",
                        (stage, now, note, app_id))
        if cur.rowcount != 1:
            return False
        c.execute("INSERT INTO app_events (application_id, at, kind, note) "
                  "VALUES (?,?,?,?)", (app_id, now, f"stage:{stage}", note or None))
    return True


def add_app_event(app_id: int, kind: str, note: str = "") -> None:
    with tx() as c:
        c.execute("INSERT INTO app_events (application_id, at, kind, note) "
                  "VALUES (?,?,?,?)", (app_id, _now(), kind, note or None))


def app_events(app_id: int) -> list[dict]:
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM app_events WHERE application_id=? ORDER BY at", (app_id,))]


def funnel_counts() -> dict:
    with ro() as c:
        rows = c.execute("SELECT stage, COUNT(*) n FROM applications GROUP BY stage")
        counts = {r["stage"] or "applied": r["n"] for r in rows}
    return {s: counts.get(s, 0) for s in STAGES}


def followups_due(now: Optional[float] = None, days: int = FOLLOWUP_AFTER_DAYS) -> list[dict]:
    """Applications with no answer after a week. The app never sends these —
    it writes the reminder and the template; Yonatan sends them."""
    now = now if now is not None else _now()
    cutoff = now - days * 86400
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM applications WHERE stage='applied' AND sent_at <= ? "
            "AND (next_action_at IS NULL OR next_action_at <= ?) "
            "ORDER BY sent_at LIMIT 50", (cutoff, now))]


def snooze_followup(app_id: int, days: int = 7) -> None:
    with tx() as c:
        c.execute("UPDATE applications SET next_action_at=? WHERE id=?",
                  (_now() + days * 86400, app_id))


# ------------------------------ recovery -----------------------------------

def sweep_stuck_items(older_than_s: float = 600.0) -> int:
    """Rescue items wedged in 'sending'.

    A send can stall (browser contention, a hung page) and leave an item in
    'sending' with no worker behind it — it then never resolves and is invisible
    to the assist queue. Sweep those to needs_input so a human can verify and
    finish them. NEVER to 'sent': we have no confirmation evidence, and claiming
    a send that may not have happened is the worst possible failure.
    """
    cutoff = _now() - older_than_s
    with tx() as c:
        cur = c.execute(
            "UPDATE run_items SET state='needs_input', updated_at=?, "
            "reason='send stalled — verify manually whether it was sent' "
            "WHERE state='sending' AND updated_at < ?", (_now(), cutoff))
        return cur.rowcount


def sweep_stale_runs(stale_after_s: float) -> list[int]:
    """On startup, reconcile runs whose worker died. ready stays ready (durable,
    re-preparable); preparing -> queued; sending -> needs_input (never auto-sent);
    the run itself -> interrupted. Returns the swept run ids."""
    now = _now()
    swept: list[int] = []
    with tx() as c:
        rows = c.execute(
            "SELECT id, heartbeat_at, worker_pid FROM runs "
            "WHERE status IN ('running','awaiting_confirm','sending')").fetchall()
        # (parked runs are included here on purpose: a dead worker must still
        # release their 'preparing'/'sending' items, even though a parked run
        # no longer blocks new ones.)
        for r in rows:
            hb = r["heartbeat_at"] or 0
            if (now - hb) < stale_after_s and _pid_alive(r["worker_pid"]):
                continue
            rid = r["id"]
            c.execute("UPDATE run_items SET state='queued', updated_at=? "
                      "WHERE run_id=? AND state='preparing'", (now, rid))
            c.execute("UPDATE run_items SET state='needs_input', "
                      "reason='send interrupted — verify manually', updated_at=? "
                      "WHERE run_id=? AND state='sending'", (now, rid))
            c.execute("UPDATE run_items SET confirm_token=NULL WHERE run_id=?",
                      (rid,))
            c.execute("UPDATE runs SET status='interrupted', finished_at=? "
                      "WHERE id=?", (now, rid))
            swept.append(rid)
    return swept


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False
