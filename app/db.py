"""SQLite storage: profile, jobs, applications, runs.

Single local database file at data/app.db. Uses the stdlib sqlite3 driver so
there are no extra dependencies. Connections are short-lived and created per
call; the apply runner runs in its own thread and opens its own connections.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "app.db"

# Statuses that count as "already handled" so we never re-apply.
TERMINAL_STATUSES = ("applied", "needs_review")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                full_name TEXT, first_name TEXT, last_name TEXT,
                email TEXT, phone TEXT,
                location TEXT, region TEXT,
                linkedin TEXT, github TEXT, portfolio TEXT,
                needs_sponsorship INTEGER DEFAULT 1,
                work_authorized_israel INTEGER DEFAULT 1,
                cv_path TEXT,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS job (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, company TEXT, external_id TEXT,
                title TEXT, location TEXT, url TEXT, apply_url TEXT,
                remote INTEGER DEFAULT 0,
                raw_json TEXT, fetched_at REAL,
                UNIQUE (source, company, external_id)
            );

            CREATE TABLE IF NOT EXISTS application (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, company TEXT, external_id TEXT,
                title TEXT, apply_url TEXT,
                status TEXT, reason TEXT, screenshot_path TEXT,
                created_at REAL, updated_at REAL,
                UNIQUE (source, company, external_id)
            );

            CREATE TABLE IF NOT EXISTS run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL, finished_at REAL,
                status TEXT, message TEXT, stats_json TEXT
            );

            CREATE TABLE IF NOT EXISTS app_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES application(id),
                at REAL, kind TEXT, note TEXT
            );
            """
        )
        # Follow-up tracking columns (added after initial release).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(application)")}
        if "stage" not in cols:
            conn.execute("ALTER TABLE application ADD COLUMN stage TEXT")
        if "stage_at" not in cols:
            conn.execute("ALTER TABLE application ADD COLUMN stage_at REAL")


# ----------------------------- profile -------------------------------------

PROFILE_FIELDS = [
    "full_name", "first_name", "last_name", "email", "phone",
    "location", "region", "linkedin", "github", "portfolio",
    "needs_sponsorship", "work_authorized_israel", "cv_path",
]


def get_profile() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        return dict(row) if row else None


def save_profile(data: dict) -> None:
    values = {k: data.get(k) for k in PROFILE_FIELDS}
    # Derive first/last from full name when not provided explicitly.
    if values.get("full_name") and not values.get("first_name"):
        parts = values["full_name"].split()
        values["first_name"] = parts[0] if parts else ""
        values["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    values["updated_at"] = time.time()
    cols = ", ".join(values.keys())
    placeholders = ", ".join(":" + k for k in values.keys())
    updates = ", ".join(f"{k}=excluded.{k}" for k in values.keys())
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO profile (id, {cols}) VALUES (1, {placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            values,
        )


# ------------------------------- jobs --------------------------------------

def upsert_job(job: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO job (source, company, external_id, title, location,
                             url, apply_url, remote, raw_json, fetched_at)
            VALUES (:source, :company, :external_id, :title, :location,
                    :url, :apply_url, :remote, :raw_json, :fetched_at)
            ON CONFLICT(source, company, external_id) DO UPDATE SET
                title=excluded.title, location=excluded.location,
                url=excluded.url, apply_url=excluded.apply_url,
                remote=excluded.remote, raw_json=excluded.raw_json,
                fetched_at=excluded.fetched_at
            """,
            {
                "source": job["source"],
                "company": job["company"],
                "external_id": str(job["external_id"]),
                "title": job.get("title"),
                "location": job.get("location"),
                "url": job.get("url"),
                "apply_url": job.get("apply_url"),
                "remote": 1 if job.get("remote") else 0,
                "raw_json": json.dumps(job.get("raw", {})),
                "fetched_at": time.time(),
            },
        )


# --------------------------- applications ----------------------------------

def already_handled(source: str, company: str, external_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM application "
            "WHERE source=? AND company=? AND external_id=?",
            (source, company, str(external_id)),
        ).fetchone()
        return bool(row and row["status"] in TERMINAL_STATUSES)


def record_application(job: dict, status: str, reason: str = "",
                       screenshot_path: str = "") -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO application (source, company, external_id, title,
                apply_url, status, reason, screenshot_path,
                created_at, updated_at)
            VALUES (:source, :company, :external_id, :title, :apply_url,
                :status, :reason, :screenshot_path, :now, :now)
            ON CONFLICT(source, company, external_id) DO UPDATE SET
                status=excluded.status, reason=excluded.reason,
                screenshot_path=excluded.screenshot_path,
                updated_at=excluded.updated_at
            """,
            {
                "source": job["source"],
                "company": job["company"],
                "external_id": str(job["external_id"]),
                "title": job.get("title"),
                "apply_url": job.get("apply_url"),
                "status": status,
                "reason": reason,
                "screenshot_path": screenshot_path,
                "now": now,
            },
        )


def list_applications(status: Optional[str] = None, limit: int = 200) -> list[dict]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM application WHERE status=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM application ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def application_counts() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM application GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}


# ------------------------------- runs --------------------------------------

def create_run() -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO run (started_at, status, message, stats_json) "
            "VALUES (?, 'running', '', '{}')",
            (time.time(),),
        )
        return cur.lastrowid


def update_run(run_id: int, status: str, message: str = "",
               stats: Optional[dict] = None, finished: bool = False) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE run SET status=?, message=?, stats_json=?, "
            "finished_at=COALESCE(?, finished_at) WHERE id=?",
            (
                status, message,
                json.dumps(stats or {}),
                time.time() if finished else None,
                run_id,
            ),
        )


def get_latest_run() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d.get("stats_json") or "{}")
        return d


def get_run(run_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d.get("stats_json") or "{}")
        return d


# ---------------------------- follow-up tracker -----------------------------

# Pipeline stages, in order. `stage` is NULL until the user starts tracking;
# the tracker treats submitted applications with no stage as "applied".
STAGES = ("applied", "followed_up", "replied", "interview", "offer",
          "rejected", "no_answer")


def list_tracked() -> list[dict]:
    """All applications, newest first, with their events attached."""
    with _connect() as conn:
        apps = [dict(r) for r in conn.execute(
            "SELECT * FROM application ORDER BY created_at DESC")]
        events = conn.execute(
            "SELECT * FROM app_event ORDER BY at ASC").fetchall()
    by_app: dict[int, list[dict]] = {}
    for e in events:
        by_app.setdefault(e["application_id"], []).append(dict(e))
    for a in apps:
        a["events"] = by_app.get(a["id"], [])
        if not a.get("stage") and a.get("status") == "applied":
            a["stage"] = "applied"
    return apps


def set_stage(app_id: int, stage: str, note: str = "") -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE application SET stage=?, stage_at=?, updated_at=? WHERE id=?",
            (stage, now, now, app_id),
        )
        conn.execute(
            "INSERT INTO app_event (application_id, at, kind, note) "
            "VALUES (?, ?, 'stage', ?)",
            (app_id, now, note or f"moved to {stage}"),
        )


def add_event(app_id: int, note: str, kind: str = "note") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_event (application_id, at, kind, note) "
            "VALUES (?, ?, ?, ?)",
            (app_id, time.time(), kind, note),
        )
