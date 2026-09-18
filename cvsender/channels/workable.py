"""Workable channel: public widget feed + hosted apply form.

Workable is common among Israeli startups that outgrew a careers page but did
not move to Greenhouse. The widget endpoint is public and needs no key.
"""
from __future__ import annotations

import httpx

from ..config import USER_AGENT
from . import atsform
from .base import Job

LIST_URL = "https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
APPLY_URL = "https://apply.workable.com/{token}/j/{shortcode}/apply/"
SUBMIT = ["button[type='submit']", "button:has-text('Submit')",
          "button:has-text('Submit application')", "[data-ui='submit-application']"]


def _location(job: dict) -> str:
    loc = job.get("location") or {}
    if isinstance(loc, str):
        return loc
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    return ", ".join(p for p in parts if p)


class WorkableChannel:
    channel = "workable"

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
                    r = await c.get(LIST_URL.format(token=token))
                    data = r.json() if r.status_code == 200 else {}
                    status = r.status_code
                except (httpx.HTTPError, ValueError) as e:
                    data, status = {}, f"error:{type(e).__name__}"
                listed = data.get("jobs") or []
                for j in listed:
                    code = j.get("shortcode") or j.get("id")
                    if not code:
                        continue
                    jobs.append(Job(
                        channel="workable", company=data.get("name") or token,
                        external_id=str(code), title=j.get("title", ""),
                        location=_location(j),
                        url=j.get("url") or APPLY_URL.format(token=token, shortcode=code),
                        apply_url=j.get("application_url")
                        or APPLY_URL.format(token=token, shortcode=code),
                        remote=bool(j.get("telecommuting")),
                        description=(j.get("description") or "")[:2000],
                        raw={"token": token, "shortcode": code}))
                spec.setdefault("_health", {})[f"workable:{token}"] = \
                    {"status": status, "jobs": len(listed)}
        return jobs

    async def _root(self, page):
        try:
            await page.wait_for_selector(
                "input[name='firstname'], input[name='email'], form", timeout=6000)
        except Exception:
            pass
        return page.main_frame

    async def prepare(self, ctx, job, profile, cv_path, cancel):
        return await atsform.prepare_generic(ctx, job, profile, cv_path, cancel,
                                             self._root, "workable")

    async def send(self, ctx, handle, cancel):
        return await atsform.send_generic(
            ctx, handle, cancel, self._root, SUBMIT, net_host="workable.com",
            confirm_url="thank", confirm_sel=["[data-ui='application-submitted']",
                                              "h1:has-text('Thank')"])
