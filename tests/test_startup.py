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


def test_startup_survives_a_busy_database(monkeypatch, capsys):
    """The service must come up while a run is writing.

    Measured 2026-09-22: two consecutive starts died with "database is locked"
    from sweep_stale_runs; only launchd's retry brought the server back.
    """
    import sqlite3
    from cvsender import main as m

    monkeypatch.setattr(m.store, "sweep_stale_runs",
                        lambda *_: (_ for _ in ()).throw(
                            sqlite3.OperationalError("database is locked")))
    monkeypatch.setattr(m, "migrate", lambda: None)
    monkeypatch.setattr(m, "_cloud_bg", lambda *_: None)
    monkeypatch.setattr(m.scheduler, "start", lambda: None)

    m._startup()                                   # must not raise
    assert "database busy" in capsys.readouterr().out
