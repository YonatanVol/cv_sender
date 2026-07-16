"""LinkedIn Easy Apply driver (best-effort, Playwright sync API).

This is the most fragile part of the tool by nature — LinkedIn changes its DOM
often and actively discourages automation. Behaviour is deliberately
conservative: it fills what it confidently can and, the moment a step needs an
answer it can't supply, it abandons that job and marks it ``needs_review``
rather than submitting bad data.

LOGIN: uses a persistent browser profile. On the first run you log in by hand
in the visible window; the session then persists, so later runs are automatic.
We never store your password.
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

from .fieldmap import known_question_answer, profile_values

SEARCH_BASE = "https://www.linkedin.com/jobs/search/"

# Keyword sets aimed at junior / student / entry software roles.
SEARCH_QUERIES = [
    "junior software developer",
    "student software developer",
    "software developer intern",
    "junior software engineer",
    "entry level software engineer",
]

ERROR_FEEDBACK = "artdeco-inline-feedback--error"


def is_logged_in(page) -> bool:
    try:
        page.goto("https://www.linkedin.com/feed/", timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    url = page.url.lower()
    return "/login" not in url and "/authwall" not in url and "/checkpoint" not in url


def search_easy_apply_jobs(page, location: str = "Israel", per_query: int = 15) -> list[dict]:
    """Collect Easy Apply job postings across the junior-role queries."""
    seen: dict[str, dict] = {}
    for query in SEARCH_QUERIES:
        params = {
            "keywords": query,
            "location": location,
            "f_AL": "true",          # Easy Apply only
            "f_E": "1,2",            # internship + entry level
            "sortBy": "DD",          # most recent
        }
        url = SEARCH_BASE + "?" + urlencode(params)
        try:
            page.goto(url, timeout=40000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(2500)
        except Exception:
            continue
        # Lazy list: scroll a few times to load more cards.
        for _ in range(4):
            try:
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(900)
            except Exception:
                break
        try:
            anchors = page.query_selector_all("a[href*='/jobs/view/']")
        except Exception:
            anchors = []
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
                if "/jobs/view/" not in href:
                    continue
                job_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                if not job_id or job_id in seen:
                    continue
                title = (a.inner_text() or "").strip().split("\n")[0]
                seen[job_id] = {
                    "source": "linkedin",
                    "company": "linkedin",
                    "external_id": job_id,
                    "title": title or query,
                    "location": location,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "remote": False,
                    "raw": {"query": query},
                }
            except Exception:
                continue
            if len([j for j in seen.values() if j["raw"].get("query") == query]) >= per_query:
                break
    return list(seen.values())


def _fill_modal_step(page, profile: dict) -> list[str]:
    """Fill recognized fields in the currently-visible Easy Apply step.

    Returns a list of labels for required fields it could NOT answer.
    """
    values = profile_values(profile)
    missing: list[str] = []
    scope = "div.jobs-easy-apply-content, div[role='dialog']"

    # Text inputs / textareas.
    try:
        els = page.query_selector_all(f"{scope} input[type='text'], {scope} input[type='tel'], "
                                      f"{scope} input[type='email'], {scope} textarea")
    except Exception:
        els = []
    for el in els:
        try:
            if not el.is_visible():
                continue
            label = (el.get_attribute("aria-label") or el.get_attribute("name") or "").lower()
            current = el.input_value()
            if current:
                continue  # LinkedIn often pre-fills from past applications.
            if "phone" in label or "mobile" in label:
                el.fill(values["phone"])
            elif "email" in label:
                el.fill(values["email"])
            elif "first" in label:
                el.fill(values["first_name"])
            elif "last" in label:
                el.fill(values["last_name"])
            elif "city" in label or "location" in label:
                el.fill(values["location"])
            elif "linkedin" in label:
                el.fill(values["linkedin"])
            elif "github" in label or "website" in label or "portfolio" in label:
                el.fill(values["github"] or values["portfolio"])
        except Exception:
            continue

    # Native selects (experience yes/no, authorization, etc.).
    try:
        selects = page.query_selector_all(f"{scope} select")
    except Exception:
        selects = []
    for sel in selects:
        try:
            if not sel.is_visible():
                continue
            label = (sel.get_attribute("aria-label") or "").lower()
            answer = known_question_answer(label, profile)
            if answer:
                try:
                    sel.select_option(label=answer)
                    continue
                except Exception:
                    pass
            # Unknown required dropdown -> can't safely guess.
            if sel.get_attribute("required") is not None and not sel.input_value():
                missing.append(label[:60] or "dropdown question")
        except Exception:
            continue

    # File upload (resume) if the step asks for it is handled by caller.
    return missing


def apply_easy_apply(page, job: dict, profile: dict, cv_path: str | None,
                     submit: bool) -> dict:
    """Drive the Easy Apply modal for one job.

    Returns {status, reason}. status in {submitted, needs_review, failed, filled}.
    """
    result = {"status": "needs_review", "reason": ""}
    try:
        page.goto(job["apply_url"], timeout=40000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)
    except Exception as e:
        return {"status": "failed", "reason": f"load error: {e}"[:120]}

    # Open the Easy Apply modal.
    opened = False
    for sel in ("button.jobs-apply-button",
                "button[aria-label*='Easy Apply']",
                "button:has-text('Easy Apply')"):
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                opened = True
                break
        except Exception:
            continue
    if not opened:
        return {"status": "needs_review", "reason": "no Easy Apply (external apply)"}
    page.wait_for_timeout(1800)

    # Upload CV if a file input is present at any point.
    def try_upload():
        if not cv_path:
            return
        try:
            fi = page.query_selector("input[type='file']")
            if fi:
                fi.set_input_files(cv_path)
        except Exception:
            pass

    # Step through the modal.
    for _ in range(8):
        try_upload()
        missing = _fill_modal_step(page, profile)
        if missing:
            _dismiss_modal(page)
            return {"status": "needs_review",
                    "reason": "needs answers: " + "; ".join(missing[:2])}

        # Submit?
        submit_btn = _find_button(page, ["Submit application"])
        if submit_btn:
            if not submit:
                _dismiss_modal(page)
                return {"status": "filled", "reason": "dry run (reached submit)"}
            try:
                submit_btn.click()
                page.wait_for_timeout(2500)
                return {"status": "submitted", "reason": "submitted via Easy Apply"}
            except Exception as e:
                return {"status": "failed", "reason": f"submit error: {e}"[:120]}

        # Advance.
        nxt = _find_button(page, ["Review your application", "Review",
                                  "Continue to next step", "Next"])
        if not nxt:
            _dismiss_modal(page)
            return {"status": "needs_review", "reason": "stuck (no next/submit)"}
        try:
            nxt.click()
            page.wait_for_timeout(1500)
        except Exception:
            _dismiss_modal(page)
            return {"status": "needs_review", "reason": "could not advance step"}

        # Did LinkedIn flag a required field we missed?
        try:
            if page.query_selector(f".{ERROR_FEEDBACK}"):
                _dismiss_modal(page)
                return {"status": "needs_review", "reason": "required field flagged"}
        except Exception:
            pass

    _dismiss_modal(page)
    return {"status": "needs_review", "reason": "too many steps"}


def _find_button(page, texts: list[str]):
    for t in texts:
        try:
            btn = page.query_selector(f"button[aria-label*='{t}']") or \
                  page.query_selector(f"button:has-text('{t}')")
            if btn and btn.is_visible() and btn.is_enabled():
                return btn
        except Exception:
            continue
    return None


def _dismiss_modal(page):
    """Close the Easy Apply modal and discard the draft so the next job starts clean."""
    try:
        x = page.query_selector("button[aria-label='Dismiss']")
        if x:
            x.click()
            page.wait_for_timeout(800)
        discard = _find_button(page, ["Discard"])
        if discard:
            discard.click()
            page.wait_for_timeout(500)
    except Exception:
        pass
