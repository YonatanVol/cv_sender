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

# Every score is 0-100 so a number means the same thing everywhere.
BASE = 50
BANDS = ((90, "excellent fit"), (75, "strong fit"), (60, "possible fit"),
         (40, "weak fit"), (0, "unlikely fit"))
# strictness -> minimum score to keep.
STRICTNESS = {"loose": 35, "balanced": 45, "strict": 75}   # strict = strong fit only


def band_for(score: float) -> str:
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "unlikely fit"


@dataclass
class Contribution:
    """One reason the score is what it is, in the words a human would use."""
    label: str
    points: int


@dataclass
class Verdict:
    keep: bool
    score: float               # 0-100
    stage: str                 # where it dropped: role|geography|score|kept
    reason: str = ""
    signals: list[str] = field(default_factory=list)
    contributions: list = field(default_factory=list)
    band: str = ""
    review: str = ""

    def explain(self) -> str:
        """'86 strong fit — student position +20, C++ +15, 5+ years required -12'"""
        parts = ", ".join(f"{c.label} {c.points:+d}" for c in self.contributions)
        return f"{self.score:.0f} {self.band}" + (f" — {parts}" if parts else "")


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


_SOFT_YEARS = re.compile(
    r"(preferred|advantage|a plus|nice to have|bonus|ideally|יתרון|רצוי)", re.I)
_HARD_YEARS = re.compile(r"(required|must have|minimum|at least|חובה|נדרש)", re.I)


def years_are_required(description: str) -> bool:
    """'5+ years required' is a wall; '3 years preferred' is not.

    Judged by the words around the years phrase, not the number alone, so a
    junior-friendly posting is not rejected for mentioning a preference.
    """
    if not description:
        return False
    for m in re.finditer(r"(\d+)\s*\+?\s*(?:years|year|שנות|שנים)", description, re.I):
        window = description[max(0, m.start() - 90):m.end() + 90]
        if _SOFT_YEARS.search(window):
            return False
        if _HARD_YEARS.search(window):
            return True
    return True          # bare "5+ years" reads as a requirement


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

    # --- score: start at 50 and give every move a name -------------------
    contributions: list[Contribution] = []

    def add(label: str, points: int) -> None:
        if points:
            contributions.append(Contribution(label, points))

    blob = f"{title} {desc[:1500]}".lower()

    if strong:
        add("clear software role", 5)
    jr = _has(title, K.JUNIOR_EN, K.JUNIOR_HE)
    sr = _has(title, K.SENIOR_EN, K.SENIOR_HE)
    if jr:
        add(f"{jr} role", 20)
        signals.append(f"junior:{jr}")
    if sr and not jr:
        # A junior candidate is not a fit for an explicit senior/staff/lead
        # role, however many of his skills the posting lists. This is a gate,
        # not a penalty: keyword bonuses used to outweigh it.
        signals.append(f"senior:{sr}")
        add(f"{sr} role", -30)
        return Verdict(False, max(0, min(100, BASE + sum(c.points for c in contributions))),
                       "seniority", f"{sr} role — not a junior position",
                       signals, contributions, "unlikely fit", "")
    if re.search(r"(?<![a-z0-9])(i|1)(?![a-z0-9])", title.lower()) and not sr:
        add("level I", 5)
        signals.append("level-1")
    if _has_en(blob, K.STUDENT_HINTS) or _has_he(blob, K.STUDENT_HINTS_HE):
        add("open to students", 12)

    # Skills Yonatan actually has, counted once each and capped so a long
    # keyword list can never outweigh seniority.
    matched = [name for name, needles in K.SKILL_SIGNALS
               if _has_en(blob, needles) or _has_he(blob, needles)]
    for name in matched[:4]:
        add(name, 8)
    if len(matched) > 4:
        add(f"{len(matched) - 4} more matching skills", 4)
    signals.extend(f"skill:{m}" for m in matched)

    # Years of experience: a hard requirement is a wall, a preference is not.
    yrs = min_years_required(desc)
    if yrs is not None:
        hard = years_are_required(desc)
        signals.append(f"yoe{'>=' if yrs >= 3 else '<='}{yrs}")
        if yrs <= 2:
            add("asks for 2 years or less", 15)
        elif yrs >= 5:
            add(f"{yrs}+ years {'required' if hard else 'preferred'}",
                -35 if hard else -8)
        else:
            add(f"{yrs} years {'required' if hard else 'preferred'}",
                -12 if hard else -4)

    if in_il:
        add("in Israel", 8)
    elif is_remote:
        add("remote", 4)
    if review:
        add(f"borderline: {review}", -12)

    score = max(0, min(100, BASE + sum(c.points for c in contributions)))
    band = band_for(score)
    threshold = STRICTNESS.get(strictness, STRICTNESS["balanced"])
    if score < threshold:
        return Verdict(False, score, "score",
                       f"{score:.0f} {band}, below the {strictness} bar of {threshold}",
                       signals, contributions, band, review or "")
    if review:
        signals.append(f"review:{review}")
        return Verdict(True, score, "kept",
                       f"{score:.0f} {band} — borderline role ({review}): check it fits",
                       signals, contributions, band, review)
    return Verdict(True, score, "kept", f"{score:.0f} {band}", signals,
                   contributions, band, "")
