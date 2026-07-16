"""Map a stored profile onto generic application-form fields and known
yes/no screening questions.

Everything here is heuristic and label-driven so it works across the
standardized ATS forms (Greenhouse / Lever / Ashby) without per-company code.
"""
from __future__ import annotations

# (field value key, list of substrings that identify the form field)
TEXT_FIELD_PATTERNS = [
    ("first_name", ["first name", "first_name", "given name", "forename"]),
    ("last_name", ["last name", "last_name", "surname", "family name"]),
    ("full_name", ["full name", "your name", "name"]),
    ("email", ["email", "e-mail"]),
    ("phone", ["phone", "mobile", "telephone", "cell"]),
    ("linkedin", ["linkedin"]),
    ("github", ["github", "git hub"]),
    ("portfolio", ["portfolio", "website", "personal site", "url"]),
    ("location", ["location", "city", "where are you", "current city"]),
]

# Common yes/no screening questions answered from the profile.
# (profile-derived answer, substrings identifying the question)
def known_question_answer(question: str, profile: dict) -> str | None:
    q = question.lower()
    authorized = bool(profile.get("work_authorized_israel", 1))
    needs_sponsorship = bool(profile.get("needs_sponsorship", 1))

    if "authoriz" in q and "work" in q:
        # "Are you authorized to work in Israel?" -> yes for an Israeli citizen.
        if "israel" in q:
            return "Yes" if authorized else "No"
        # Authorization for elsewhere (US/EU) -> generally no without a visa.
        return "No"
    if "sponsor" in q or "visa" in q:
        # "Do you require sponsorship?" -> yes if they need it.
        return "Yes" if needs_sponsorship else "No"
    if "relocat" in q:
        return "No"
    if "18 years" in q or "over 18" in q or "at least 18" in q:
        return "Yes"
    if "gender" in q or "race" in q or "ethnic" in q or "veteran" in q or \
            "disability" in q:
        # EEO / demographic questions -> decline to self-identify.
        return "Decline To Self Identify"
    return None


def profile_values(profile: dict) -> dict:
    """Flat dict of values used to fill text fields."""
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
