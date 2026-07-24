"""Lever channel: public postings feed + native /apply form."""
from __future__ import annotations

import httpx

from ..config import USER_AGENT
from . import atsform
from .base import Job

LIST_URL = "https://api.lever.co/v0/postings/{company}"
SUBMIT = ["button[type='submit']", "button:has-text('Submit application')",
          ".postings-btn[type='submit']", "input[type='submit']"]


class LeverChannel:
    channel = "lever"

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
                try:
                    r = await c.get(LIST_URL.format(company=token),
                                    params={"mode": "json"})
                    data = r.json() if r.status_code == 200 else []
                    status = r.status_code
                except (httpx.HTTPError, ValueError) as e:
                    data, status = [], f"error:{type(e).__name__}"
                if not isinstance(data, list):
                    data = []
                for j in data:
                    cats = j.get("categories", {}) or {}
                    loc = cats.get("location", "") or ""
                    hosted = j.get("hostedUrl", "")
                    jobs.append(Job(
                        channel="lever", company=token,
                        external_id=str(j.get("id")), title=j.get("text", ""),
                        location=loc, url=hosted,
                        apply_url=j.get("applyUrl") or (hosted + "/apply"),
                        remote=(cats.get("workplaceType", "").lower() == "remote"),
                        description=j.get("descriptionPlain", "")[:2000],
                        raw={"id": j.get("id")}))
                spec.setdefault("_health", {})[f"lever:{token}"] = \
                    {"status": status, "jobs": len(data)}
        return jobs

    async def _root(self, page):
        try:
            await page.wait_for_selector(
                "input[name='name'], input[name='email'], form.application-form",
                timeout=6000)
        except Exception:
            pass
        return page.main_frame

    async def prepare(self, ctx, job, profile, cv_path, cancel):
        return await atsform.prepare_generic(ctx, job, profile, cv_path, cancel,
                                             self._root, "lever")

    async def send(self, ctx, handle, cancel):
        return await atsform.send_generic(
            ctx, handle, cancel, self._root, SUBMIT, net_host="lever.co",
            confirm_url="thank", confirm_sel=[".application-confirmation",
                                              "[data-qa='confirmation']"])
