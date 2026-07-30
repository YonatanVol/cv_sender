"""Self-driving runner: it must top up to the target, stop when there's nothing
new, and NEVER submit anything on its own."""
import pytest

import cvsender.config as config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    store.save_profile({"full_name": "T", "email": "t@x.com",
                        "cv_path": str(tmp_path / "cv.pdf")})
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 test")
    return store


def test_stops_when_target_already_staged(db, monkeypatch):
    from cvsender import runner
    monkeypatch.setattr(runner, "queue_depth", lambda: 100)
    called = []
    monkeypatch.setattr(runner, "stage_batch",
                        lambda *a, **k: called.append(1) or ("done", 0))
    rc = runner.run(target=100, loop=False, channels=["greenhouse"],
                    geography="israel_remote", strictness="balanced",
                    concurrency=2, batch=40, sleep_s=0)
    assert rc == 0
    assert not called, "must not stage when the target is already met"


def test_stages_when_below_target(db, monkeypatch):
    from cvsender import runner
    depths = iter([10, 35])                      # before, after
    monkeypatch.setattr(runner, "queue_depth", lambda: next(depths))
    seen = {}

    def fake_stage(cap, channels, geo, strict, conc):
        seen["cap"] = cap
        return "awaiting_confirm", 25
    monkeypatch.setattr(runner, "stage_batch", fake_stage)
    rc = runner.run(target=100, loop=False, channels=["greenhouse"],
                    geography="israel_remote", strictness="balanced",
                    concurrency=2, batch=40, sleep_s=0)
    assert rc == 0
    assert seen["cap"] == 40, "should stage a batch, bounded by --batch"


def test_refuses_without_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty.db")
    from cvsender.db.migrations import migrate
    from cvsender import runner
    migrate()
    rc = runner.run(target=10, loop=False, channels=["greenhouse"],
                    geography="israel_remote", strictness="balanced",
                    concurrency=1, batch=10, sleep_s=0)
    assert rc == 2, "must refuse to run without a profile + CV"


def test_stage_batch_never_uses_live_mode(db, monkeypatch):
    """The runner prepares only — a send must always require a human confirm."""
    from cvsender import runner
    captured = {}
    monkeypatch.setattr(runner.store, "create_run_atomic",
                        lambda options, mode: captured.update(
                            options=options, mode=mode) or None)
    runner.stage_batch(10, ["greenhouse"], "israel_remote", "balanced", 2)
    assert captured["mode"] == "dry"
    assert captured["options"]["mode"] == "dry"
