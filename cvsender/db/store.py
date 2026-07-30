"""Typed data-access for v2. Every write is short and one-shot; the run/item
state machine and dedupe invariants live here so callers can't violate them.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Sequence

from .connection import connect, ro, tx

ACTIVE_STATUSES = ("running", "awaiting_confirm", "sending")


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
            "('running','awaiting_confirm','sending'))",
            (json.dumps(options), mode, os.getpid(), now, now),
        )
        return cur.lastrowid if cur.rowcount == 1 else None


def get_run(run_id: int) -> Optional[dict]:
    with ro() as c:
        return _row(c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def get_active_run() -> Optional[dict]:
    with ro() as c:
        return _row(c.execute(
            "SELECT * FROM runs WHERE status IN ('running','awaiting_confirm',"
            "'sending') ORDER BY id DESC LIMIT 1").fetchone())


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


# --------------------------- daily counters --------------------------------

def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def bump_daily(channel: str) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO daily_counts (day, channel, sent) VALUES (?,?,1) "
            "ON CONFLICT(day, channel) DO UPDATE SET sent = sent + 1",
            (_today(), channel))


def sent_today(channel: Optional[str] = None) -> int:
    with ro() as c:
        if channel:
            r = c.execute("SELECT sent FROM daily_counts WHERE day=? AND channel=?",
                          (_today(), channel)).fetchone()
            return r["sent"] if r else 0
        r = c.execute("SELECT COALESCE(SUM(sent),0) n FROM daily_counts WHERE day=?",
                      (_today(),)).fetchone()
        return r["n"] if r else 0


# --------------------------- assist queue ----------------------------------

def assist_queue(limit: int = 200) -> list[dict]:
    """Everything a human could finish right now: filled-but-blocked items,
    newest first, excluding anything already sent (dedupe by key)."""
    with ro() as c:
        return [dict(r) for r in c.execute(
            "SELECT i.* FROM run_items i "
            "WHERE i.state IN ('needs_input','failed','ready') "
            "  AND NOT EXISTS (SELECT 1 FROM applications a "
            "                  WHERE a.dedupe_key = i.dedupe_key) "
            "GROUP BY i.dedupe_key "
            "ORDER BY (i.state='ready') DESC, i.score DESC, i.id DESC LIMIT ?",
            (limit,)).fetchall()]


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


def record_application(item: dict, evidence: str) -> int:
    """Idempotent terminal write — only call with real confirmation evidence."""
    now = _now()
    with tx() as c:
        cur = c.execute(
            "INSERT INTO applications (dedupe_key, content_hash, channel, company, "
            "title, apply_url, status, confirmation_evidence, run_id, item_id, "
            "sent_at, stage, stage_at) VALUES (?,?,?,?,?,?, 'sent', ?,?,?,?, "
            "'applied', ?) ON CONFLICT(dedupe_key) DO NOTHING",
            (item["dedupe_key"], item.get("content_hash"), item["channel"],
             item.get("company"), item.get("title"), item.get("apply_url"),
             evidence, item.get("run_id"), item["id"], now, now),
        )
        return cur.lastrowid


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
