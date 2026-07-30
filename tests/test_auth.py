"""Auth guards endpoints that fire real, irreversible job applications."""
import time

import pytest

import cvsender.config as config


@pytest.fixture()
def a(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender import auth
    migrate()
    auth._sessions.clear()
    auth._failures.clear()
    auth.clear_passphrase()
    return auth


def test_not_configured_by_default(a):
    assert a.is_configured() is False
    assert a.verify_passphrase("anything") is False


def test_set_and_verify(a):
    a.set_passphrase("correct horse battery")
    assert a.is_configured() is True
    assert a.verify_passphrase("correct horse battery") is True
    assert a.verify_passphrase("wrong") is False


def test_passphrase_never_stored_in_plaintext(a):
    from cvsender.db import store
    secret = "super secret phrase"
    a.set_passphrase(secret)
    stored = store.get_setting(a.SETTING_KEY)
    assert secret not in stored
    assert stored.startswith("scrypt$")


def test_short_passphrase_rejected(a):
    with pytest.raises(ValueError):
        a.set_passphrase("short")
    assert a.is_configured() is False


def test_salt_is_unique_per_set(a):
    from cvsender.db import store
    a.set_passphrase("the same phrase")
    first = store.get_setting(a.SETTING_KEY)
    a.set_passphrase("the same phrase")
    assert store.get_setting(a.SETTING_KEY) != first, "salt must be random"


def test_sessions(a):
    t = a.create_session()
    assert a.valid_session(t) is True
    assert a.valid_session("forged-token") is False
    a.destroy_session(t)
    assert a.valid_session(t) is False


def test_expired_session_rejected(a):
    t = a.create_session()
    a._sessions[t] = time.time() - 1
    assert a.valid_session(t) is False


def test_rate_limiting(a):
    client = "1.2.3.4"
    assert a.locked_out(client) == 0
    for _ in range(a.MAX_FAILURES):
        a.note_failure(client)
    assert a.locked_out(client) > 0, "must lock out after repeated failures"
    a.clear_failures(client)
    assert a.locked_out(client) == 0


def test_clearing_passphrase_kills_sessions(a):
    a.set_passphrase("passphrase here")
    t = a.create_session()
    a.clear_passphrase()
    assert a.valid_session(t) is False
