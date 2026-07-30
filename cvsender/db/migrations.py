"""Ordered migrations keyed on PRAGMA user_version (a real runner, not v1's
ad-hoc 'ALTER TABLE IF column missing' checks)."""
from __future__ import annotations

from .connection import connect

# Each entry is applied in order; index+1 becomes the new user_version.
MIGRATIONS: list[str] = [
    # 001 — full v2 schema
    """
    CREATE TABLE profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        full_name TEXT, first_name TEXT, last_name TEXT,
        email TEXT, phone TEXT,
        location TEXT, region TEXT,
        linkedin TEXT, github TEXT, portfolio TEXT,
        needs_sponsorship INTEGER NOT NULL DEFAULT 0,
        work_authorized_il INTEGER NOT NULL DEFAULT 1,
        cv_path TEXT, cv_sha256 TEXT, cv_name TEXT,
        cv_size INTEGER, cv_pages INTEGER,
        extra_answers_json TEXT NOT NULL DEFAULT '{}',
        updated_at REAL
    );

    CREATE TABLE runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        options_json TEXT NOT NULL DEFAULT '{}',
        mode TEXT NOT NULL DEFAULT 'dry' CHECK (mode IN ('dry','live')),
        phase TEXT NOT NULL DEFAULT 'prepare' CHECK (phase IN ('prepare','send')),
        status TEXT NOT NULL DEFAULT 'running'
            CHECK (status IN ('running','awaiting_confirm','sending','done',
                              'cancelled','error','interrupted')),
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        worker_pid INTEGER,
        heartbeat_at REAL,
        message TEXT,
        started_at REAL, finished_at REAL
    );

    CREATE TABLE run_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        channel TEXT NOT NULL,
        company TEXT, title TEXT, location TEXT,
        url TEXT, apply_url TEXT,
        dedupe_key TEXT NOT NULL,
        content_hash TEXT,
        score REAL, score_json TEXT,
        state TEXT NOT NULL DEFAULT 'queued'
            CHECK (state IN ('queued','preparing','ready','needs_input',
                             'sending','sent','sent_unverified','failed',
                             'skipped','cancelled')),
        attempts INTEGER NOT NULL DEFAULT 0,
        reason TEXT,
        result_json TEXT,
        screenshot_prepare TEXT,
        screenshot_after TEXT,
        confirmation_evidence TEXT,
        confirm_token TEXT,
        created_at REAL, updated_at REAL,
        UNIQUE (run_id, dedupe_key)
    );

    CREATE TABLE run_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        item_id INTEGER REFERENCES run_items(id) ON DELETE CASCADE,
        at REAL,
        level TEXT NOT NULL DEFAULT 'info'
            CHECK (level IN ('debug','info','warn','error')),
        type TEXT NOT NULL,
        message TEXT,
        data_json TEXT
    );

    CREATE TABLE applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dedupe_key TEXT NOT NULL UNIQUE,
        content_hash TEXT,
        channel TEXT, company TEXT, title TEXT, apply_url TEXT,
        status TEXT NOT NULL DEFAULT 'sent' CHECK (status = 'sent'),
        confirmation_evidence TEXT,
        run_id INTEGER REFERENCES runs(id),
        item_id INTEGER REFERENCES run_items(id),
        sent_at REAL,
        stage TEXT, stage_at REAL
    );

    CREATE TABLE app_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
        at REAL, kind TEXT, note TEXT
    );

    CREATE INDEX idx_items_run_state  ON run_items(run_id, state);
    CREATE INDEX idx_items_dedupe     ON run_items(dedupe_key);
    CREATE INDEX idx_events_run_id    ON run_events(run_id, id);
    CREATE INDEX idx_runs_status      ON runs(status);
    CREATE INDEX idx_apps_dedupe      ON applications(dedupe_key);
    CREATE INDEX idx_apps_content     ON applications(content_hash);
    CREATE INDEX idx_appev_app        ON app_events(application_id, at);
    """,

    # 002 — answer bank (learn a screening answer once, reuse forever),
    # user-confirmed sends, and daily send counters for the daily target/caps.
    """
    CREATE TABLE answer_bank (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qkey TEXT NOT NULL UNIQUE,     -- normalized question text
        question TEXT,                 -- original label, for display
        answer TEXT NOT NULL,
        kind TEXT DEFAULT 'text',
        uses INTEGER NOT NULL DEFAULT 0,
        created_at REAL, updated_at REAL
    );
    CREATE INDEX idx_answers_qkey ON answer_bank(qkey);

    -- Daily counters: enforce per-channel caps + the daily target.
    CREATE TABLE daily_counts (
        day TEXT NOT NULL,             -- YYYY-MM-DD (local)
        channel TEXT NOT NULL,
        sent INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, channel)
    );

    -- Assist tracking. run_items.state has a CHECK constraint that can't be
    -- altered in place (and other tables FK to it), so "handed to the human"
    -- is a nullable column rather than a new state: the item stays in
    -- needs_input/failed and assist_at marks that it is in the burst queue.
    ALTER TABLE run_items ADD COLUMN assist_at REAL;
    """,

    # 003 — app settings (passphrase hash for remote access, misc config).
    """
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at REAL
    );
    """,

    # 004 — jobs the user has permanently dismissed (expired postings, or ones
    # they never want offered again). Kept separate from `applications` so they
    # never count as sent, but consulted by the same dedupe path so they stop
    # being re-staged on every future run.
    """
    CREATE TABLE dismissed (
        dedupe_key TEXT PRIMARY KEY,
        content_hash TEXT,
        kind TEXT NOT NULL DEFAULT 'unavailable',
        company TEXT, title TEXT,
        at REAL
    );
    CREATE INDEX idx_dismissed_hash ON dismissed(content_hash);
    """,
]


def migrate() -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i in range(version, len(MIGRATIONS)):
            conn.executescript(MIGRATIONS[i])
            conn.execute(f"PRAGMA user_version = {i + 1}")
        final = conn.execute("PRAGMA user_version").fetchone()[0]
        return final
    finally:
        conn.close()
