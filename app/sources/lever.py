"""Lever public Postings API.

List endpoint (no auth):
    GET https://api.lever.co/v0/postings/{company}?mode=json

Docs: https://github.com/lever/postings-api
"""
from __future__ import annotations

import httpx

BASE = "https://api.lever.co/v0/postings/{company}"


def _looks_remote(text: str) -> bool:
    return "remote" in (text or "").lower()


def fetch_company_jobs(token: str, client: httpx.Client | None = None) -> list[dict]:
    owns_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(BASE.format(company=token), params={"mode": "json"})
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns_client:
            client.close()

    jobs = []
    for j in data:
        categories = j.get("categories", {}) or {}
        location = categories.get("location", "") or ""
        workplace = categories.get("workplaceType", "") or ""
        jobs.append({
            "source": "lever",
            "company": token,
            "external_id": str(j.get("id")),
            "title": j.get("text", ""),
            "location": location,
            "url": j.get("hostedUrl", ""),
            "apply_url": j.get("applyUrl") or (j.get("hostedUrl", "") + "/apply"),
            "remote": workplace.lower() == "remote" or _looks_remote(location),
            "raw": j,
        })
    return jobs
