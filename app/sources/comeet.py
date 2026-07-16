"""Comeet public careers API (popular with Israeli employers).

Comeet careers pages are embedded per-company and expose:
    GET https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}

The (uid, token) pair is visible in the careers-page embed snippet. In
boards.yaml a Comeet entry is therefore written as "uid:token". Entries that
don't contain a ':' (or that error) are skipped so the run never breaks.
"""
from __future__ import annotations

import httpx

BASE = "https://www.comeet.co/careers-api/2.0/company/{uid}/positions"


def _looks_remote(text: str) -> bool:
    return "remote" in (text or "").lower()


def fetch_company_jobs(token: str, client: httpx.Client | None = None) -> list[dict]:
    if ":" not in (token or ""):
        return []
    uid, api_token = token.split(":", 1)

    owns_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(BASE.format(uid=uid), params={"token": api_token})
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns_client:
            client.close()

    jobs = []
    for j in data if isinstance(data, list) else []:
        loc = j.get("location", {}) or {}
        location = ", ".join(
            p for p in [loc.get("city"), loc.get("country")] if p
        ) or loc.get("name", "")
        jobs.append({
            "source": "comeet",
            "company": uid,
            "external_id": str(j.get("uid") or j.get("id")),
            "title": j.get("name", ""),
            "location": location,
            "url": j.get("url_active_page", "") or j.get("url_comeet_hosted_page", ""),
            "apply_url": j.get("url_active_page", "") or j.get("url_comeet_hosted_page", ""),
            "remote": _looks_remote(location) or _looks_remote(j.get("name", "")),
            "raw": j,
        })
    return jobs
