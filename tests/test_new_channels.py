"""Workable and SmartRecruiters: parse public feeds into Jobs, offline."""
import asyncio

import pytest

from cvsender.channels.smartrecruiters import SmartRecruitersChannel
from cvsender.channels.workable import WorkableChannel


class FakeResponse:
    def __init__(self, payload, status=200): self._p, self.status_code = payload, status
    def json(self): return self._p


class FakeClient:
    """Stands in for httpx.AsyncClient; returns one canned payload."""
    def __init__(self, payload, status=200): self._p, self._s = payload, status
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None): return FakeResponse(self._p, self._s)


def _patch(monkeypatch, module, payload, status=200):
    monkeypatch.setattr(module.httpx, "AsyncClient",
                        lambda *a, **k: FakeClient(payload, status))


def test_workable_parses_jobs(monkeypatch):
    import cvsender.channels.workable as mod
    _patch(monkeypatch, mod, {"name": "Acme", "jobs": [
        {"shortcode": "ABC123", "title": "Junior Backend Engineer",
         "location": {"city": "Tel Aviv", "country": "Israel"},
         "telecommuting": True, "description": "python"},
        {"title": "no shortcode — skipped"}]})
    jobs = asyncio.run(WorkableChannel(["acme"]).discover({}))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.channel == "workable" and j.company == "Acme"
    assert j.external_id == "ABC123" and j.remote is True
    assert j.location == "Tel Aviv, Israel"
    assert j.apply_url == "https://apply.workable.com/acme/j/ABC123/apply/"
    assert j.dedupe_key == "workable:acme:ABC123"


def test_smartrecruiters_parses_postings(monkeypatch):
    import cvsender.channels.smartrecruiters as mod
    _patch(monkeypatch, mod, {"totalFound": 1, "content": [
        {"id": "7440", "name": "Software Engineer",
         "company": {"name": "Gong"},
         "location": {"city": "Ramat Gan", "country": "Israel", "remote": False}}]})
    jobs = asyncio.run(SmartRecruitersChannel(["Gong"]).discover({}))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Gong" and j.external_id == "7440"
    assert j.apply_url == "https://jobs.smartrecruiters.com/Gong/7440"
    assert j.location == "Ramat Gan, Israel"


@pytest.mark.parametrize("channel,module_name", [
    (WorkableChannel, "cvsender.channels.workable"),
    (SmartRecruitersChannel, "cvsender.channels.smartrecruiters"),
])
def test_a_dead_board_is_recorded_not_raised(monkeypatch, channel, module_name):
    import importlib
    mod = importlib.import_module(module_name)
    _patch(monkeypatch, mod, {}, status=404)
    spec = {}
    assert asyncio.run(channel(["nope"]).discover(spec)) == []
    assert list(spec["_health"].values())[0]["status"] == 404


def test_both_channels_are_registered():
    from cvsender.channels.registry import BUILDERS, build_adapters
    assert {"workable", "smartrecruiters"} <= set(BUILDERS)
    built = build_adapters({"channels": ["workable", "smartrecruiters"]})
    assert set(built) == {"workable", "smartrecruiters"}
