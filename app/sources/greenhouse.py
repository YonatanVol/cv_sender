"""Greenhouse public Job Board API.

List endpoint (no auth):
    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Docs: https://developers.greenhouse.io/job-board.html
"""
from __future__ import annotations

import httpx

BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _looks_remote(location: str) -> bool:
    return "remote" in (location or "").lower()


def fetch_company_jobs(token: str, client: httpx.Client | None = None) -> list[dict]:
    """Return normalized jobs for a Greenhouse board token.

    Unknown/invalid tokens (404) and network errors return [] so a bad entry
    in the seed list never breaks a whole run.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(BASE.format(token=token), params={"content": "true"})
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
        location = (j.get("location") or {}).get("name", "") or ""
        url = j.get("absolute_url", "")
        jobs.append({
            "source": "greenhouse",
            "company": token,
            "external_id": str(j.get("id")),
            "title": j.get("title", ""),
            "location": location,
            "url": url,
            "apply_url": url,  # the hosted form lives at the posting URL
            "remote": _looks_remote(location),
            "raw": j,
        })
    return jobs
