"""Comeet channel (Israeli ATS). Tokens are 'uid:token' pairs extracted from a
company's careers-page embed."""
from __future__ import annotations

import httpx

from ..config import USER_AGENT
from . import atsform
from .base import Job

LIST_URL = "https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
SUBMIT = ["button[type='submit']", "button:has-text('Submit')",
          "button:has-text('Apply')"]


class ComeetChannel:
    channel = "comeet"

    def __init__(self, tokens: list[str]):
        self.tokens = tokens

    async def discover(self, spec: dict) -> list[Job]:
        ct = spec.get("_cancel")
        jobs: list[Job] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as c:
            for token in self.tokens:
                if ct:
                    ct.check()
                if ":" not in token:
                    continue
                uid, api = token.split(":", 1)
                try:
                    r = await c.get(LIST_URL.format(uid=uid), params={"token": api})
                    data = r.json() if r.status_code == 200 else []
                    status = r.status_code
                except (httpx.HTTPError, ValueError) as e:
                    data, status = [], f"error:{type(e).__name__}"
                if not isinstance(data, list):
                    data = []
                for j in data:
                    loc = j.get("location", {}) or {}
                    location = ", ".join(p for p in [loc.get("city"),
                                                     loc.get("country")] if p) \
                        or loc.get("name", "")
                    url = j.get("url_active_page") or j.get("url_comeet_hosted_page", "")
                    jobs.append(Job(
                        channel="comeet", company=uid,
                        external_id=str(j.get("uid") or j.get("id")),
                        title=j.get("name", ""), location=location,
                        url=url, apply_url=url,
                        description=(j.get("description") or "")[:2000],
                        raw={"uid": j.get("uid")}))
                spec.setdefault("_health", {})[f"comeet:{uid}"] = \
                    {"status": status, "jobs": len(data)}
        return jobs

    async def _root(self, page):
        try:
            await page.wait_for_selector("input, form", timeout=7000)
        except Exception:
            pass
        return page.main_frame

    async def prepare(self, ctx, job, profile, cv_path, cancel):
        return await atsform.prepare_generic(ctx, job, profile, cv_path, cancel,
                                             self._root, "comeet")

    async def send(self, ctx, handle, cancel):
        return await atsform.send_generic(
            ctx, handle, cancel, self._root, SUBMIT, net_host="comeet",
            confirm_url="thank", confirm_sel=["[class*='confirmation']",
                                              "[class*='thank']"])
