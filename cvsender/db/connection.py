"""SQLite connection factory with the pragmas v1 forgot to enforce.

Short-lived connections, one unit of work each. WAL for concurrent readers
(the SSE stream + API) alongside the single worker writer; foreign keys ON so
the run -> run_items -> run_events cascade actually holds; busy_timeout so a
brief writer lock retries instead of raising.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .. import config


def connect() -> sqlite3.Connection:
    # Read config.DB_PATH dynamically so tests can point at a temp DB.
    conn = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """A transactional connection: commits on success, rolls back on error."""
    conn = connect()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def ro() -> Iterator[sqlite3.Connection]:
    """A read-only connection (no explicit transaction)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
