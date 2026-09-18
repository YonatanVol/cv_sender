"""Pick the CV that fits the posting.

One CV for every job buries the half that matters: a QA lead should meet the
test harnesses first, a backend team the Python services. So the same true
content is built into a few role variants, and the posting decides which one
goes out. Nothing here writes or invents CV content — it only chooses a file
that already exists and was reviewed once.

Deterministic keyword scoring, so the choice is explainable and identical every
time. Falls back to the default CV whenever nothing matches clearly.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from .db import store

# Variant name -> the words in a posting that call for it. These are the role
# families Yonatan's CV can honestly speak to.
FAMILIES: dict[str, list[str]] = {
    "backend": ["backend", "back-end", "back end", "server-side", "api", "apis",
                "fastapi", "django", "flask", "node.js", "microservice",
                "distributed", "python", "java", "go ", "golang", "בקאנד",
                "שרת", "צד שרת"],
    "fullstack": ["full stack", "fullstack", "full-stack", "frontend", "front-end",
                  "front end", "react", "next.js", "typescript", "javascript",
                  "web developer", "ui ", "פולסטאק", "פול סטאק", "פרונט"],
    "qa": ["qa", "quality assurance", "test automation", "automation engineer",
           "sdet", "testing", "selenium", "cypress", "playwright", "pytest",
           "בדיקות", "אוטומציית בדיקות"],
    "data": ["data engineer", "data analyst", "analytics", "sql", "etl", "bi ",
             "machine learning", "ml ", "algorithm", "pandas", "warehouse",
             "דאטה", "נתונים", "אלגוריתמ"],
}


def _text(job_title: str, description: str = "") -> str:
    return f" {(job_title or '').lower()} {(description or '').lower()[:1500]} "


TITLE_WEIGHT, BODY_WEIGHT = 3, 1


def score_families(job_title: str, description: str = "") -> dict[str, int]:
    """How strongly each family is called for.

    The title is what the role IS; the description mentions everything the team
    touches. So a title word outweighs several body words, and "Backend
    Engineer" whose description mentions Cypress still gets the backend CV.
    """
    title = _text(job_title)
    body = _text("", description)
    scores: dict[str, int] = {}
    for family, needles in FAMILIES.items():
        n = 0
        for w in needles:
            pattern = re.escape(w.strip())
            if re.search(rf"(?<![a-z]){pattern}(?![a-z])", title):
                n += TITLE_WEIGHT
            elif re.search(rf"(?<![a-z]){pattern}(?![a-z])", body):
                n += BODY_WEIGHT
        scores[family] = n
    return scores


def pick(job_title: str, description: str = "",
         variants: Optional[list[dict]] = None) -> Optional[dict]:
    """The best variant for this posting, or the default, or None."""
    variants = variants if variants is not None else store.list_cv_variants()
    usable = [v for v in variants if v.get("path") and Path(v["path"]).exists()]
    if not usable:
        return None
    default = next((v for v in usable if v.get("is_default")), usable[0])
    scores = score_families(job_title, description)
    best_family, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score < TITLE_WEIGHT:            # nothing clearly called for
        return default
    tied = [f for f, s in scores.items() if s == best_score]
    if len(tied) > 1:                        # ambiguous: don't guess
        return default
    match = next((v for v in usable
                  if v["name"] == best_family or best_family in (v.get("tags") or [])), None)
    return match or default


def cv_for(job_title: str, description: str = "") -> tuple[str, str]:
    """(path, variant_name) for a posting; ('', '') when no variant exists."""
    v = pick(job_title, description)
    return (v["path"], v["name"]) if v else ("", "")


def sha256(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""
