"""Ashby channel: public posting API + React application form (best-effort;
the form is an SPA, so unrecognized layouts route to needs_input rather than a
false send)."""
from __future__ import annotations

import httpx

from ..config import USER_AGENT
from . import atsform
from .base import Job

LIST_URL = "https://api.ashbyhq.com/posting-api/job-board/{company}"
SUBMIT = ["button[type='submit']", "button:has-text('Submit Application')",
          "button:has-text('Submit application')"]


class AshbyChannel:
    channel = "ashby"

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
                    r = await c.get(LIST_URL.format(company=token))
                    data = r.json() if r.status_code == 200 else {}
                    status = r.status_code
                except (httpx.HTTPError, ValueError) as e:
                    data, status = {}, f"error:{type(e).__name__}"
                items = data.get("jobs", []) if isinstance(data, dict) else []
                for j in items:
                    loc = j.get("location", "") or ""
                    url = j.get("jobUrl", "") or j.get("applyUrl", "")
                    jobs.append(Job(
                        channel="ashby", company=token,
                        external_id=str(j.get("id")), title=j.get("title", ""),
                        location=loc, url=url,
                        apply_url=j.get("applyUrl") or url,
                        remote=bool(j.get("isRemote")),
                        description=(j.get("descriptionPlain")
                                    or j.get("description", ""))[:2000],
                        raw={"id": j.get("id")}))
                spec.setdefault("_health", {})[f"ashby:{token}"] = \
                    {"status": status, "jobs": len(items)}
        return jobs

    async def _root(self, page):
        try:
            await page.wait_for_selector("input, form", timeout=7000)
        except Exception:
            pass
        return page.main_frame

    async def prepare(self, ctx, job, profile, cv_path, cancel):
        return await atsform.prepare_generic(ctx, job, profile, cv_path, cancel,
                                             self._root, "ashby")

    async def send(self, ctx, handle, cancel):
        return await atsform.send_generic(
            ctx, handle, cancel, self._root, SUBMIT, net_host="ashbyhq.com",
            confirm_url="", confirm_sel=["[class*='confirmation']",
                                         "[class*='Success']"])
