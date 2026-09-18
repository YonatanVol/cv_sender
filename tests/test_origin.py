"""Origin allow-list: the phone must work, forged origins must not."""
import socket

import pytest

import cvsender.config as config


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from cvsender.db.migrations import migrate
    migrate()
    from cvsender import main
    return main


def test_lan_origin_allowed_while_bound_to_all_interfaces(app_mod, monkeypatch):
    """--remote binds 0.0.0.0; the phone sends the Mac's LAN IP as Origin."""
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    lan = socket.getaddrinfo(socket.gethostname(), None)[0][4][0]
    lan = f"[{lan}]" if ":" in lan else lan
    assert f"http://{lan}:{config.PORT}" in app_mod.local_origins()
    assert f"http://0.0.0.0:{config.PORT}" not in app_mod.local_origins()


def test_loopback_always_allowed(app_mod):
    o = app_mod.local_origins()
    assert f"http://127.0.0.1:{config.PORT}" in o
    assert f"http://localhost:{config.PORT}" in o


def test_public_origin_setting_is_honoured(app_mod):
    from cvsender.db import store
    store.set_setting("public_origin", "https://mac.tailnet.ts.net/")
    assert "https://mac.tailnet.ts.net" in app_mod.local_origins()


def test_foreign_origin_rejected(app_mod):
    from fastapi import HTTPException

    class Req:                       # minimal stand-in for a Starlette request
        def __init__(self, origin): self.headers = {"origin": origin} if origin else {}
    app_mod._check_origin(Req(None))                      # curl: no Origin, fine
    app_mod._check_origin(Req(f"http://localhost:{config.PORT}"))
    for bad in ("http://evil.example:8010", "http://127.0.0.1.evil.example:8010",
                f"http://localhost:{config.PORT + 1}"):
        with pytest.raises(HTTPException) as e:
            app_mod._check_origin(Req(bad))
        assert e.value.status_code == 403
