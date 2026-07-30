"""Maps a profile to form values + known screening answers, with a HARD refusal
for prohibited fields (passwords, government IDs, financial). These are never
filled — an account-creation wall or credential field forces a block, never a
guess. EEO questions only ever get 'decline to self-identify'."""
from __future__ import annotations

import re

# Label patterns we must NEVER auto-fill. Presence forces a block.
PROHIBITED = [
    r"password", r"\bssn\b", r"social security", r"passport", r"national id",
    r"government id", r"תעודת זהות", r"ת\.ז", r"תז\b",
    r"bank", r"iban", r"credit card", r"card number", r"routing",
    r"cvv", r"payment", r"salary expectation.*bank",
]
_PROHIBITED_RX = re.compile("|".join(PROHIBITED), re.I)

# Text field patterns -> profile value key (checked in order; specific first).
TEXT_FIELDS = [
    ("first_name", ["first name", "first_name", "given name", "שם פרטי"]),
    ("last_name", ["last name", "last_name", "surname", "family name", "שם משפחה"]),
    ("full_name", ["full name", "your name", "שם מלא", "name"]),
    ("email", ["email", "e-mail", "אימייל", "דוא"]),
    ("phone", ["phone", "mobile", "telephone", "cell", "טלפון", "נייד"]),
    ("linkedin", ["linkedin"]),
    ("github", ["github"]),
    ("portfolio", ["portfolio", "website", "personal site", "אתר"]),
    ("location", ["location", "city", "current city", "עיר", "מיקום"]),
]


def is_prohibited(label: str) -> bool:
    return bool(_PROHIBITED_RX.search(label or ""))


def profile_values(profile: dict) -> dict:
    return {
        "first_name": profile.get("first_name") or "",
        "last_name": profile.get("last_name") or "",
        "full_name": profile.get("full_name") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "linkedin": profile.get("linkedin") or "",
        "github": profile.get("github") or "",
        "portfolio": profile.get("portfolio") or "",
        "location": profile.get("location") or "",
    }


def match_text_field(field_key: str) -> str | None:
    """Return the profile value-key whose patterns match this field's label blob."""
    k = (field_key or "").lower()
    for value_key, needles in TEXT_FIELDS:
        if any(n in k for n in needles):
            return value_key
    return None


def known_answer(question: str, profile: dict) -> str | None:
    """Answer a common yes/no or EEO screening question, or None if we won't
    guess (which routes it to needs_input for the human).

    Order: never answer prohibited fields → a previously LEARNED answer (the
    human answered this exact question before) → built-in rules. Pure lookup +
    rules; no AI, so a send costs nothing."""
    q = (question or "").lower()
    if is_prohibited(q):
        return None

    # Learned answers win: the human already told us this once.
    try:
        from ..db import store
        learned = store.recall_answer(question)
        if learned:
            store.bump_answer_use(question)
            return learned
    except Exception:
        pass  # DB unavailable -> fall back to rules
    authorized = bool(profile.get("work_authorized_il", 1))
    needs_sponsorship = bool(profile.get("needs_sponsorship", 0))

    if ("authoriz" in q or "eligible" in q or "right to work" in q) and "work" in q:
        if "israel" in q or "ישראל" in q:
            return "Yes" if authorized else "No"
        return "No"                       # authorization elsewhere -> generally no
    if "sponsor" in q or "visa" in q or "אשרה" in q:
        return "Yes" if needs_sponsorship else "No"
    if "relocat" in q or "עבור דירה" in q:
        return "No"
    if "over 18" in q or "at least 18" in q or "18 years" in q:
        return "Yes"
    if any(t in q for t in ("gender", "race", "ethnic", "veteran", "disability",
                            "hispanic", "מגדר", "מוצא")):
        return "Decline To Self Identify"   # never fabricate a protected trait
    return None
