"""Is this posting still open?

41% of the queue was older than 30 days and nothing knew whether those jobs
still existed. Two sampled July postings turned out to redirect to an empty
board — the "no recognized form fields" they reported was really "this job is
gone". A dead posting at the top of the queue wastes the only scarce resource
in this system, which is Yonatan's attention.

Verification is a plain HTTP GET, never a browser: cheap, and it cannot be
mistaken for application traffic. Closed postings are dismissed (kind='closed'),
so they leave the queue and stay in history. Nothing is ever deleted.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import USER_AGENT
from .db import store

ACTIVE, STALE, CLOSED, UNKNOWN = "active", "stale", "closed", "unknown"

FRESH_DAYS = 7          # seen this recently: trusted without a check
RECHECK_DAYS = 14       # older than this must be re-verified before being offered
TIMEOUT_S = 15.0

# Phrases boards use when a posting is gone.
_GONE_TEXT = re.compile(
    r"(?:\bno longer accepting\b|\bno longer available\b|"
    r"\bposition (?:is )?closed\b|\bthis job is closed\b|"
    r"\bjob has been filled\b|\bposting (?:is|has) (?:closed|expired)\b|"
    r"\bnot accepting applications\b|"
    r"המשרה אינה|המשרה נסגרה|המשרה אויישה)", re.I)
_GONE_URL = re.compile(r"[?&]error=true|/jobs/?$|/careers/?$|/search\b", re.I)


def parse_posted(value) -> Optional[float]:
    """Epoch seconds from whatever shape a board reports a date in."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v          # milliseconds vs seconds
    text = str(value).strip()
    if text.isdigit():
        return parse_posted(int(text))
    try:
        cleaned = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text[:19], fmt).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def relative_posted(text: str, now: Optional[float] = None) -> Optional[float]:
    """LinkedIn cards say '3 days ago' / 'לפני שבועיים' instead of a date."""
    if not text:
        return None
    now = now if now is not None else time.time()
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", text, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        seconds = {"minute": 60, "hour": 3600, "day": 86400,
                   "week": 604800, "month": 2592000}[unit]
        return now - n * seconds
    if re.search(r"just posted|today|היום", text, re.I):
        return now
    m = re.search(r"לפני\s*(\d+)?\s*(דקות|שעות|יומיים|ימים|שבועיים|שבועות|שבוע|"
                  r"חודשיים|חודשים|חודש)", text)
    if m:
        unit = m.group(2)
        # Hebrew has a dual form: שבועיים is two weeks, not one.
        n = int(m.group(1) or (2 if unit.endswith("יים") else 1))
        seconds = (60 if "דק" in unit else 3600 if "שע" in unit else
                   86400 if "ימים" in unit else 604800 if "שבוע" in unit else 2592000)
        return now - n * seconds
    return None


def classify(status_code: int, final_url: str, body: str, asked_url: str) -> str:
    """What the HTTP response says about the posting's existence."""
    if status_code in (404, 410):
        return CLOSED
    if status_code >= 500 or status_code in (0, 403, 429):
        return UNKNOWN                       # the board is unhappy, not the job
    # Phrase matching is the most dangerous rule here: a loose fragment once
    # dismissed live jobs because it matched inside ordinary words. Only match
    # whole phrases, and only in the page's own text.
    if _GONE_TEXT.search(body or ""):
        return CLOSED
    asked_id = re.search(r"/(\d{4,})", asked_url or "")
    if asked_id and asked_id.group(1) not in (final_url or ""):
        # Redirected away from the posting: a board root, a careers page, or an
        # error flag means it is gone; anywhere else we cannot be sure.
        if _GONE_URL.search(final_url or ""):
            return CLOSED
        return UNKNOWN
    return ACTIVE if status_code == 200 else UNKNOWN


def check_url(url: str, client: Optional[httpx.Client] = None) -> str:
    """One liveness probe. Never raises."""
    if not url:
        return UNKNOWN
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    try:
        r = client.get(url)
        return classify(r.status_code, str(r.url), r.text[:20000], url)
    except httpx.HTTPError:
        return UNKNOWN
    finally:
        if own:
            client.close()


def needs_check(item: dict, now: Optional[float] = None) -> bool:
    """True when this posting is too old to be trusted without a fresh check."""
    now = now if now is not None else time.time()
    if (item.get("liveness") or UNKNOWN) == CLOSED:
        return False                          # already settled
    checked = item.get("checked_at") or 0
    if now - checked < 86400:
        return False                          # checked within a day
    seen = item.get("last_seen_at") or item.get("updated_at") or 0
    return (now - seen) > RECHECK_DAYS * 86400


def verify_item(item: dict, client: Optional[httpx.Client] = None) -> str:
    """Probe one posting and record the verdict. Closed ones leave the queue."""
    verdict = check_url(item.get("apply_url") or item.get("url") or "", client)
    store.set_liveness(item["id"], verdict)
    if verdict == CLOSED:
        store.dismiss(item, kind="closed", note="verified gone")
        store.transition_item(item["id"], ["needs_input", "failed", "ready"],
                              "skipped", reason="posting is closed")
    return verdict


def sweep(limit: int = 25) -> dict:
    """Verify the stalest postings. Rate-limited by `limit` per call."""
    counts = {ACTIVE: 0, CLOSED: 0, UNKNOWN: 0}
    items = [i for i in store.assist_queue(limit=1000) if needs_check(i)][:limit]
    if not items:
        return counts
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        for item in items:
            verdict = verify_item(item, client)
            counts[verdict] = counts.get(verdict, 0) + 1
    return counts
