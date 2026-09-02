"""The app must actually boot: a decorator applied to the wrong function
(regression: a helper inserted between @on_event and _startup) took the
server down with a TypeError during lifespan."""
import cvsender.config as config


def test_app_lifespan_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("CVS_HOST", raising=False)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})   # no network
    with TestClient(main.app) as c:
        assert c.get("/login").status_code == 200
