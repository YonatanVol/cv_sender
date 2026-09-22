"""Which of Yonatan's two addresses belongs on this application.

He lives in Zichron Ya'akov and in Tel Aviv–Jaffa. That is not a detail: a
recruiter in Haifa reads "Tel Aviv" as an hour and a half each way and stops
reading, and one in Tel Aviv reads "Zichron Ya'akov" the same way. So the
address follows the posting, the way the CV variant already follows the role —
same person, the true half of the answer that the reader needs.

Both addresses are real, so neither is a lie; picking between them is the same
judgement he would make himself before typing it into the form.
"""
from __future__ import annotations

from .db import store

# Offered as the placeholder in Settings, never applied on its own.
SUGGESTED_NORTH = "Zichron Ya'akov, Israel"

# From Hadera up: the Haifa bay, the Carmel coast and the Galilee. Deliberately
# spelled out rather than matched on "kiryat" or "district", because Kiryat Gat
# is in the south and Kiryat Ono is in the centre.
NORTH_EN = [
    "haifa", "matam", "zichron", "zikhron", "binyamina", "pardes hanna",
    "hadera", "or akiva", "caesarea", "atlit", "nesher", "tirat carmel",
    "tirat hacarmel", "yokneam", "yoqneam", "migdal haemek", "migdal ha'emek",
    "karmiel", "carmiel", "afula", "nahariya", "akko", "acre", "nazareth",
    "tiberias", "kiryat ata", "kiryat bialik", "kiryat motzkin", "kiryat yam",
    "kiryat haim", "kiryat tivon", "north district", "northern district",
    "haifa district", "galilee", "krayot",
]
NORTH_HE = [
    "חיפה", "מת\"ם", "מת״ם", "זכרון יעקב", "זיכרון יעקב", "בנימינה",
    "פרדס חנה", "חדרה", "אור עקיבא", "קיסריה", "עתלית", "נשר", "טירת כרמל",
    "יקנעם", "מגדל העמק", "כרמיאל", "עפולה", "נהריה", "עכו", "נצרת",
    "טבריה", "קריית אתא", "קרית אתא", "קריית ביאליק", "קרית ביאליק",
    "קריית מוצקין", "קרית מוצקין", "קריית ים", "קרית ים", "קריית טבעון",
    "קרית טבעון", "הקריות", "הגליל", "מחוז חיפה", "מחוז הצפון",
]


def is_north(job_location: str) -> bool:
    """True when the posting sits in the Haifa bay, the Carmel coast or above."""
    loc = (job_location or "").lower()
    if not loc.strip():
        return False
    return any(p in loc for p in NORTH_EN) or any(p in loc for p in NORTH_HE)


def base_for(job_location: str, profile: dict | None = None) -> str:
    """The address to put on this application.

    The second address is a setting and defaults to empty, because no constant
    in a source file should decide where someone lives. Until it is filled in,
    every application carries the one address on the profile.
    """
    profile = profile or {}
    home_base = profile.get("location") or ""
    if not is_north(job_location):
        return home_base
    return (store.get_setting("home.base_north") or "").strip() or home_base


def profile_for(job_location: str, profile: dict) -> dict:
    """The profile as this one employer should see it: same person, near address."""
    base = base_for(job_location, profile)
    if not base or base == profile.get("location"):
        return profile
    return {**profile, "location": base}
