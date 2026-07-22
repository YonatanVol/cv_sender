"""Scored, Hebrew-aware, description-based relevance.

v1 rejected any title lacking an explicit English junior word (5,629 -> 11).
v2 scores signals: an unlabeled 'Software Engineer' is neutral (kept by default);
explicit senior/lead is strongly negative; the job DESCRIPTION's years-of-
experience is parsed. A strictness knob maps to the minimum score to keep.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import keywords as K

# strictness -> minimum score to keep. Lower = more inclusive.
STRICTNESS = {"loose": -3, "balanced": 0, "strict": 3}


@dataclass
class Verdict:
    keep: bool
    score: float
    stage: str                 # where it dropped: role|geography|score|kept
    reason: str = ""
    signals: list[str] = field(default_factory=list)


def _has_en(text: str, words: list[str]) -> Optional[str]:
    """Word-boundary match for English (kills intern in International)."""
    t = text.lower()
    for w in words:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t):
            return w
    return None


def _has_he(text: str, words: list[str]) -> Optional[str]:
    for w in words:
        if w in text:
            return w
    return None


def _has(text: str, en: list[str], he: list[str]) -> Optional[str]:
    return _has_en(text, en) or _has_he(text, he)


_YEARS = [
    re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*\+?\s*years", re.I),
    re.compile(r"(\d+)\s*\+\s*years", re.I),
    re.compile(r"at least\s*(\d+)\s*years", re.I),
    re.compile(r"minimum\s*(?:of\s*)?(\d+)\s*years", re.I),
    re.compile(r"(\d+)\s*years?\s*of\s*(?:relevant\s*)?experience", re.I),
    re.compile(r"(\d+)\s*[-–]?\s*(\d+)?\s*שנות?\s*ניסיון"),
]


def min_years_required(description: str) -> Optional[int]:
    """Smallest years-of-experience figure mentioned, or None."""
    if not description:
        return None
    best: Optional[int] = None
    for rx in _YEARS:
        for m in rx.finditer(description):
            nums = [int(g) for g in m.groups() if g and g.isdigit()]
            if not nums:
                continue
            low = min(nums)
            best = low if best is None else min(best, low)
    return best


def score_job(job, mode: str = "israel_remote",
              strictness: str = "balanced") -> Verdict:
    title = job.title or ""
    desc = job.description or ""
    loc = job.location or ""
    signals: list[str] = []

    # --- role gate ---
    if not _has(title, K.ROLE_EN, K.ROLE_HE) and not _has(desc[:600], K.ROLE_EN, K.ROLE_HE):
        return Verdict(False, 0, "role", "not a software role")

    # --- geography gate ---
    in_il = bool(_has(loc, K.ISRAEL_HINTS_EN, K.ISRAEL_HINTS_HE)) or \
        bool(_has(title, K.ISRAEL_HINTS_EN, K.ISRAEL_HINTS_HE))
    is_remote = bool(job.remote) or bool(_has_en(loc, K.REMOTE_HINTS)) or \
        bool(_has_he(loc, K.REMOTE_HINTS))
    unknown_loc = not loc.strip()
    if mode == "israel_only":
        geo_ok = in_il
    elif mode == "anywhere":
        geo_ok = True
    else:  # israel_remote
        geo_ok = in_il or is_remote or unknown_loc
    if not geo_ok:
        return Verdict(False, 0, "geography", "outside Israel and not remote")

    # --- seniority scoring ---
    score = 0.0
    jr = _has(title, K.JUNIOR_EN, K.JUNIOR_HE)
    sr = _has(title, K.SENIOR_EN, K.SENIOR_HE)
    if jr:
        score += 3
        signals.append(f"junior:{jr}")
    if sr and not jr:
        score -= 4
        signals.append(f"senior:{sr}")
    if re.search(r"(?<![a-z0-9])(i|1)(?![a-z0-9])", title.lower()) and not sr:
        score += 1
        signals.append("level-1")

    yrs = min_years_required(desc)
    if yrs is not None:
        if yrs <= 2:
            score += 2
            signals.append(f"yoe<={yrs}")
        elif yrs >= 5:
            score -= 3
            signals.append(f"yoe>={yrs}")
        elif yrs >= 3:
            score -= 1
            signals.append(f"yoe={yrs}")

    threshold = STRICTNESS.get(strictness, 0)
    if score < threshold:
        return Verdict(False, score, "score",
                       f"score {score:g} below {strictness} threshold {threshold}",
                       signals)
    return Verdict(True, score, "kept", "match", signals)
