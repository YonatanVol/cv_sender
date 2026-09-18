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


def _has_he_word(text: str, words: list[str]) -> Optional[str]:
    """Hebrew match anchored at a word start, allowing the one-letter prefixes
    ו/ה/ב/ל/מ/ש/כ. Without the anchor 'רכז' (coordinator) matches 'מרכז'
    (center) — except when מ is itself a prefix, which we accept."""
    for w in words:
        if re.search(r"(?<![\u05d0-\u05ea])[והבלש]?" + re.escape(w), text):
            return w
    return None


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

    # --- role gate (title-based for precision; description is used only for
    # seniority/YoE below, so a 'Public Policy Intern' JD that mentions software
    # doesn't sneak in) ---
    strong = _has(title, K.ROLE_STRONG_EN, K.ROLE_STRONG_HE)
    weak = _has(title, K.ROLE_WEAK_EN, K.ROLE_WEAK_HE)
    non_sw = _has_en(title, K.NON_SOFTWARE_EN) or \
        _has_he_word(title, K.NON_SOFTWARE_HE)
    if non_sw and not strong:
        return Verdict(False, 0, "role", f"not a software role ({non_sw})")
    if not strong and not weak:
        return Verdict(False, 0, "role", "not a software role")
    review: Optional[str] = None
    borderline = _has_en(title, K.BORDERLINE_EN) or \
        _has_he_word(title, K.BORDERLINE_HE)
    if borderline:
        review = borderline
    elif non_sw:
        review = non_sw
    elif not strong:
        review = weak

    # --- geography gate ---
    in_il = bool(_has(loc, K.ISRAEL_HINTS_EN, K.ISRAEL_HINTS_HE)) or \
        bool(_has(title, K.ISRAEL_HINTS_EN, K.ISRAEL_HINTS_HE))
    is_remote = bool(job.remote) or bool(_has_en(loc, K.REMOTE_HINTS)) or \
        bool(_has_he(loc, K.REMOTE_HINTS))
    unknown_loc = not loc.strip()
    # "Remote (US)" is not remote for someone in Tel Aviv.
    foreign = next((p for p in K.FOREIGN_PLACES if p in loc.lower()), None)
    inclusive = any(r in loc.lower() for r in K.INCLUSIVE_REGIONS)
    if foreign and not in_il and not inclusive:
        is_remote = False
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
    if review:
        signals.append(f"review:{review}")
        return Verdict(True, score, "kept", f"borderline role ({review}): review before sending", signals)
    return Verdict(True, score, "kept", "match", signals)
