"""Ashby public Job Posting API.

List endpoint (no auth):
    GET https://api.ashbyhq.com/posting-api/job-board/{company}

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
"""
from __future__ import annotations

import httpx

BASE = "https://api.ashbyhq.com/posting-api/job-board/{company}"


def fetch_company_jobs(token: str, client: httpx.Client | None = None) -> list[dict]:
    owns_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(BASE.format(company=token))
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns_client:
            client.close()

    jobs = []
    for j in data.get("jobs", []):
        location = j.get("location", "") or ""
        is_remote = bool(j.get("isRemote")) or "remote" in location.lower()
        url = j.get("jobUrl", "") or j.get("applyUrl", "")
        jobs.append({
            "source": "ashby",
            "company": token,
            "external_id": str(j.get("id")),
            "title": j.get("title", ""),
            "location": location,
            "url": url,
            "apply_url": j.get("applyUrl") or url,
            "remote": is_remote,
            "raw": j,
        })
    return jobs
