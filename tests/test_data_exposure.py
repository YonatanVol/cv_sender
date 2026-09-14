"""The data directory holds secrets; only form screenshots may be served."""
import pytest

import cvsender.config as config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    shots = tmp_path / "shots"; shots.mkdir()
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots)
    (shots / "form_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (shots / "notes.txt").write_text("x")
    (tmp_path / "cloud.json").write_text('{"owner": "secret"}')
    (tmp_path / "cvsender.db").write_bytes(b"SQLite format 3")
    cookies = tmp_path / "linkedin_profile" / "Default"; cookies.mkdir(parents=True)
    (cookies / "Cookies").write_bytes(b"li_at")
    monkeypatch.delenv("CVS_HOST", raising=False)
    from fastapi.testclient import TestClient
    from cvsender import cloud, main
    monkeypatch.setattr(cloud, "sync_on_start", lambda: {})
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize("path", [
    "/data2/cloud.json", "/data2/cvsender.db",
    "/data2/linkedin_profile/Default/Cookies",
    "/data2/shots/../cloud.json", "/data2/shots/..%2Fcloud.json",
    "/data2/shots/notes.txt",
])
def test_secrets_are_never_served(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert b"secret" not in r.content and b"li_at" not in r.content


def test_screenshots_still_served(client):
    r = client.get("/data2/shots/form_1.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
