"""SmartRecruiters channel: public postings API + hosted apply form."""
from __future__ import annotations

import httpx

from .. import freshness
from ..config import USER_AGENT
from . import atsform
from .base import Job

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
VIEW_URL = "https://jobs.smartrecruiters.com/{token}/{posting_id}"
SUBMIT = ["button[type='submit']", "button:has-text('Submit')",
          "button:has-text('I'm interested')", "[data-test='submit-application']"]
PAGE = 100


class SmartRecruitersChannel:
    channel = "smartrecruiters"

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
                    r = await c.get(LIST_URL.format(token=token),
                                    params={"limit": PAGE})
                    data = r.json() if r.status_code == 200 else {}
                    status = r.status_code
                except (httpx.HTTPError, ValueError) as e:
                    data, status = {}, f"error:{type(e).__name__}"
                listed = data.get("content") or []
                for j in listed:
                    pid = j.get("id")
                    if not pid:
                        continue
                    loc = j.get("location") or {}
                    where = ", ".join(p for p in (loc.get("city"), loc.get("region"),
                                                  loc.get("country")) if p)
                    url = VIEW_URL.format(token=token, posting_id=pid)
                    jobs.append(Job(
                        channel="smartrecruiters",
                        company=(j.get("company") or {}).get("name") or token,
                        external_id=str(pid), title=j.get("name", ""),
                        location=where, url=url, apply_url=url,
                        remote=bool(loc.get("remote")),
                        posted_at=freshness.parse_posted(j.get("releasedDate")),
                        description=(j.get("jobAd") or {}).get("sections", {}).get(
                            "jobDescription", {}).get("text", "")[:2000]
                        if isinstance(j.get("jobAd"), dict) else "",
                        raw={"token": token, "id": pid}))
                spec.setdefault("_health", {})[f"smartrecruiters:{token}"] = \
                    {"status": status, "jobs": data.get("totalFound", len(listed))}
        return jobs

    async def _root(self, page):
        try:
            await page.wait_for_selector(
                "input[name='firstName'], input[type='email'], form", timeout=6000)
        except Exception:
            pass
        return page.main_frame

    async def prepare(self, ctx, job, profile, cv_path, cancel):
        return await atsform.prepare_generic(ctx, job, profile, cv_path, cancel,
                                             self._root, "smartrecruiters")

    async def send(self, ctx, handle, cancel):
        return await atsform.send_generic(
            ctx, handle, cancel, self._root, SUBMIT,
            net_host="smartrecruiters.com", confirm_url="thank",
            confirm_sel=["[data-test='application-submitted']",
                         "h1:has-text('Thank')"])
