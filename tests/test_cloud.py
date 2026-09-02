"""Cloud sync: the local DB is the truth, the cloud is a mirror that must
never break the app, and a fresh device bootstraps itself from it."""
import json
import os
import types

import httpx
import pytest

import cvsender.config as config


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "CV_DIR", tmp_path / "cv")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    from cvsender import cloud
    migrate()
    monkeypatch.setattr(cloud, "CLOUD_FILE", tmp_path / "cloud.json")
    calls = []

    def fake_post(url, **kw):
        calls.append(("POST", url, kw))
        return types.SimpleNamespace(status_code=201, json=lambda: [])

    def fake_get(url, **kw):
        calls.append(("GET", url, kw))
        return types.SimpleNamespace(status_code=200, json=lambda: [], content=b"")
    monkeypatch.setattr(cloud.httpx, "post", fake_post)
    monkeypatch.setattr(cloud.httpx, "get", fake_get)
    return types.SimpleNamespace(cloud=cloud, store=store, calls=calls, tmp=tmp_path)


def test_owner_secret_is_generated_and_protected(env):
    cfg = env.cloud.load_config()
    assert len(cfg["owner"]) >= 24
    assert oct(os.stat(env.cloud.CLOUD_FILE).st_mode & 0o777) == "0o600"
    assert env.cloud.load_config()["owner"] == cfg["owner"]      # stable


def test_push_profile_carries_owner_and_upserts(env):
    env.store.save_profile({"full_name": "Y", "email": "y@x.com"})
    assert env.cloud.push_profile() is True
    m, url, kw = env.calls[-1]
    assert m == "POST" and url.endswith("/rest/v1/app_profile")
    assert kw["headers"]["x-cvs-owner"] == env.cloud.load_config()["owner"]
    assert "merge-duplicates" in kw["headers"]["Prefer"]
    assert kw["json"]["email"] == "y@x.com"


def test_network_failure_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("dns")
    monkeypatch.setattr(env.cloud.httpx, "post", boom)
    monkeypatch.setattr(env.cloud.httpx, "get", boom)
    env.store.save_profile({"email": "y@x.com"})
    assert env.cloud.push_profile() is False
    assert env.cloud.pull_profile() is None
    assert env.cloud.pull_settings() == {}
    assert "error" not in env.cloud.sync_on_start()   # degrades, doesn't crash


def test_restore_bootstraps_empty_device(env, monkeypatch):
    remote = {"full_name": "Cloud Y", "email": "cloud@x.com", "phone": "1",
              "location": "TLV", "linkedin": None, "github": None,
              "portfolio": None, "needs_sponsorship": False,
              "work_authorized_il": True, "cv_path": None}
    def fake_get(url, **kw):
        if "app_profile" in url:
            return types.SimpleNamespace(status_code=200, json=lambda: [remote])
        if "app_settings" in url:
            return types.SimpleNamespace(status_code=200,
                                         json=lambda: [{"key": "strictness", "value": "strict"}])
        return types.SimpleNamespace(status_code=200, json=lambda: [], content=b"")
    monkeypatch.setattr(env.cloud.httpx, "get", fake_get)
    out = env.cloud.restore(overwrite=False)
    assert out["profile"] is True and out["settings"] == 1
    assert env.store.get_profile()["email"] == "cloud@x.com"
    assert env.store.get_setting("run.strictness") == "strict"


def test_restore_does_not_clobber_existing_device(env, monkeypatch):
    env.store.save_profile({"full_name": "Local", "email": "local@x.com"})
    env.store.set_setting("run.strictness", "loose")
    remote = {"full_name": "Cloud", "email": "cloud@x.com", "cv_path": None}
    monkeypatch.setattr(env.cloud.httpx, "get", lambda url, **kw: types.SimpleNamespace(
        status_code=200,
        json=lambda: ([remote] if "app_profile" in url
                      else [{"key": "strictness", "value": "strict"}] if "app_settings" in url
                      else []), content=b""))
    out = env.cloud.restore(overwrite=False)
    assert out["profile"] is False and out["settings"] == 0
    assert env.store.get_profile()["email"] == "local@x.com"
    assert env.store.get_setting("run.strictness") == "loose"
    # explicit restore: cloud wins
    out = env.cloud.restore(overwrite=True)
    assert out["profile"] is True
    assert env.store.get_profile()["email"] == "cloud@x.com"


def test_prohibited_answers_are_not_restored(env, monkeypatch):
    """A leaked/odd cloud row must not smuggle a credential into the answer bank."""
    monkeypatch.setattr(env.cloud.httpx, "get", lambda url, **kw: types.SimpleNamespace(
        status_code=200, json=lambda: (
            [{"question": "Password", "answer": "hunter2", "uses": 0},
             {"question": "Years of experience", "answer": "1", "uses": 0}]
            if "app_answers" in url else []), content=b""))
    env.cloud.restore(overwrite=False)
    assert env.store.recall_answer("Password") is None
    assert env.store.recall_answer("Years of experience") == "1"


def test_download_cv_rejects_non_pdf(env, monkeypatch):
    monkeypatch.setattr(env.cloud.httpx, "get", lambda url, **kw: types.SimpleNamespace(
        status_code=200, content=b"<html>not a pdf</html>", json=lambda: []))
    dest = env.tmp / "cv" / "cv.pdf"
    assert env.cloud.download_cv(str(dest)) is False
    assert not dest.exists()


def test_cv_is_encrypted_at_rest_and_bound_to_owner(env):
    cfg = env.cloud.load_config()
    pdf = b"%PDF-1.7 hello"
    blob = env.cloud.encrypt_cv(pdf, cfg)
    assert blob.startswith(b"CVS1") and b"%PDF" not in blob
    assert env.cloud.decrypt_cv(blob, cfg) == pdf
    assert env.cloud.decrypt_cv(blob, {**cfg, "owner": "someone-else"}) is None
    assert env.cloud.decrypt_cv(blob[:-1] + b"x", cfg) is None          # tamper
    # what leaves the machine is the ciphertext, never the PDF
    src = env.tmp / "cv.pdf"; src.write_bytes(pdf)
    assert env.cloud.upload_cv(str(src)) is True
    m, url, kw = [c for c in env.calls if c[0] == "POST"][-1]
    assert url.endswith("/cv.enc") and kw["content"].startswith(b"CVS1")
    assert pdf not in kw["content"]


def test_download_cv_decrypts_round_trip(env, monkeypatch):
    cfg = env.cloud.load_config()
    pdf = b"%PDF-1.7 round trip"
    blob = env.cloud.encrypt_cv(pdf, cfg)
    monkeypatch.setattr(env.cloud.httpx, "get", lambda url, **kw: types.SimpleNamespace(
        status_code=200, content=blob, json=lambda: []))
    dest = env.tmp / "cv" / "cv.pdf"
    assert env.cloud.download_cv(str(dest)) is True
    assert dest.read_bytes() == pdf
