"""Single-user authentication for remote access.

The app's confirm endpoints fire **real, irreversible** job applications, so the
moment it is reachable beyond localhost it must be authenticated. Design:

* passphrase hashed with **scrypt** (stdlib — no extra dependency), never stored
  or logged in plaintext
* sessions are server-side random tokens held in memory, so they are invalidated
  by a restart and there is no signing secret to leak
* failed logins are rate-limited per client
* auth is **optional on loopback** (so local use is unchanged) and **mandatory**
  the moment the server binds to anything else — enforced at startup
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from .db import store

SETTING_KEY = "auth_passphrase"
COOKIE = "cvs_session"
SESSION_TTL_S = 30 * 24 * 3600          # 30 days; cleared on restart anyway
MIN_LEN = 8

# token -> expiry. In-memory on purpose: a restart logs everyone out.
_sessions: dict[str, float] = {}
# client -> (failures, first_failure_at)
_failures: dict[str, tuple[int, float]] = {}
MAX_FAILURES = 8
LOCKOUT_S = 300.0

_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32


def _hash(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                          n=_N, r=_R, p=_P, dklen=_DKLEN)


def is_configured() -> bool:
    return bool(store.get_setting(SETTING_KEY))


def set_passphrase(passphrase: str) -> None:
    if len(passphrase or "") < MIN_LEN:
        raise ValueError(f"passphrase must be at least {MIN_LEN} characters")
    salt = os.urandom(16)
    store.set_setting(SETTING_KEY,
                      f"scrypt${salt.hex()}${_hash(passphrase, salt).hex()}")


def clear_passphrase() -> None:
    store.set_setting(SETTING_KEY, None)
    _sessions.clear()


def verify_passphrase(passphrase: str) -> bool:
    stored = store.get_setting(SETTING_KEY)
    if not stored:
        return False
    try:
        algo, salt_hex, want_hex = stored.split("$", 2)
        if algo != "scrypt":
            return False
        got = _hash(passphrase or "", bytes.fromhex(salt_hex))
        return hmac.compare_digest(got, bytes.fromhex(want_hex))
    except Exception:
        return False


# ------------------------------ rate limit --------------------------------

def locked_out(client: str) -> float:
    """Seconds remaining in a lockout, or 0."""
    n, first = _failures.get(client, (0, 0.0))
    if n < MAX_FAILURES:
        return 0.0
    remaining = LOCKOUT_S - (time.time() - first)
    if remaining <= 0:
        _failures.pop(client, None)
        return 0.0
    return remaining


def note_failure(client: str) -> None:
    n, first = _failures.get(client, (0, time.time()))
    if time.time() - first > LOCKOUT_S:
        n, first = 0, time.time()
    _failures[client] = (n + 1, first)


def clear_failures(client: str) -> None:
    _failures.pop(client, None)


# ------------------------------- sessions ---------------------------------

def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL_S
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if exp < time.time():
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)
