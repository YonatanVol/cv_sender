"""Job sources: each module exposes fetch_company_jobs(token) -> list[dict].

Normalized job dict shape:
    {
        "source": "greenhouse" | "lever" | "ashby" | "comeet",
        "company": "<board token / company slug>",
        "external_id": "<stable id within that board>",
        "title": str,
        "location": str,
        "url": str,          # public job posting URL
        "apply_url": str,    # hosted application form URL
        "remote": bool,
        "raw": dict,         # original payload, for debugging
    }
"""
from . import greenhouse, lever, ashby, comeet  # noqa: F401

FETCHERS = {
    "greenhouse": greenhouse.fetch_company_jobs,
    "lever": lever.fetch_company_jobs,
    "ashby": ashby.fetch_company_jobs,
    "comeet": comeet.fetch_company_jobs,
}
