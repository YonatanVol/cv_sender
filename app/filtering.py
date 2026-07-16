"""Relevance filtering: keep junior/student software roles in Israel or remote.

A job passes only if it matches ALL of:
  - software/dev role (title keywords)
  - junior / entry / student / intern seniority (and NOT senior/lead/etc.)
  - geography: Israel or remote  (configurable via profile.region / mode)
"""
from __future__ import annotations

import re

ROLE_KEYWORDS = [
    "software", "developer", "engineer", "programmer", "frontend",
    "front-end", "front end", "backend", "back-end", "back end",
    "full stack", "fullstack", "full-stack", "web", "mobile", "android",
    "ios", "data engineer", "devops", "qa", "automation", "sde",
    "machine learning", "ml engineer", "algorithm", "embedded",
]

# Strong signals this is a junior/student/entry role.
JUNIOR_KEYWORDS = [
    "junior", "jr.", "entry level", "entry-level", "new grad", "new-grad",
    "newgrad", "graduate", "grad ", "intern", "internship", "student",
    "associate", "trainee", "apprentice", "early career", "early-career",
    "campus",
]

# If any of these appear it is NOT a junior role (unless overridden by a
# junior keyword, which we check first).
SENIOR_KEYWORDS = [
    "senior", "sr.", "staff", "principal", "lead ", "team lead", "tech lead",
    "manager", "director", "head of", "vp ", "architect", "expert",
    " iii", " iv", " v ", "ii ", "level 2", "level 3", "ii)", "iii)",
]

ISRAEL_KEYWORDS = [
    "israel", "tel aviv", "tel-aviv", "tlv", "herzliya", "herzeliya",
    "haifa", "jerusalem", "ramat gan", "petah tikva", "petach tikva",
    "raanana", "ra'anana", "netanya", "beer sheva", "be'er sheva",
    "rehovot", "yokneam", "caesarea", "kiryat",
]


def _has_any(text: str, needles: list[str]) -> bool:
    t = f" {text.lower()} "
    return any(n in t for n in needles)


def is_software_role(title: str) -> bool:
    return _has_any(title, ROLE_KEYWORDS)


def is_junior(title: str) -> bool:
    t = f" {title.lower()} "
    if _has_any(title, JUNIOR_KEYWORDS):
        return True
    # No explicit junior signal: accept only if it's clearly not senior and
    # carries a "I" / level-1 marker, otherwise treat as ambiguous -> reject.
    if _has_any(title, SENIOR_KEYWORDS):
        return False
    if re.search(r"\b(i|1)\b", t) and is_software_role(title):
        return True
    return False


def is_senior(title: str) -> bool:
    return _has_any(title, SENIOR_KEYWORDS) and not _has_any(title, JUNIOR_KEYWORDS)


def matches_geography(job: dict, mode: str = "israel_remote") -> bool:
    """mode: 'israel_remote' | 'israel_only' | 'anywhere'."""
    location = (job.get("location") or "")
    remote = bool(job.get("remote")) or _has_any(location, ["remote"])
    in_israel = _has_any(location, ISRAEL_KEYWORDS)
    if mode == "anywhere":
        return True
    if mode == "israel_only":
        return in_israel
    return in_israel or remote  # israel_remote (default)


def relevance(job: dict, mode: str = "israel_remote") -> tuple[bool, str]:
    """Return (keep, reason). reason explains a rejection for debugging."""
    title = job.get("title", "") or ""
    if not is_software_role(title):
        return False, "not a software role"
    if is_senior(title):
        return False, "senior/lead role"
    if not is_junior(title):
        return False, "not clearly junior/student/entry"
    if not matches_geography(job, mode):
        return False, "outside Israel and not remote"
    return True, "match"


def filter_jobs(jobs: list[dict], mode: str = "israel_remote") -> list[dict]:
    return [j for j in jobs if relevance(j, mode)[0]]
