"""Generic, label-driven application-form filler (Playwright sync API).

Works across the standardized hosted forms (Greenhouse / Lever / Ashby):
fills native text inputs/textareas by matching their label/name/placeholder,
uploads the CV to the resume file input, answers native <select> screening
questions it recognizes, and routes anything uncertain to "needs_review".

It deliberately does NOT try to guess answers to free-text essay questions or
custom dropdown widgets — those are queued for the human instead of submitting
low-quality data.
"""
from __future__ import annotations

from ..fieldmap import TEXT_FIELD_PATTERNS, profile_values, known_question_answer

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[title*='captcha']",
    ".g-recaptcha",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit Application')",
    "button:has-text('Submit application')",
    "button:has-text('Submit')",
    "button:has-text('Apply')",
]

CONFIRMATION_TEXTS = [
    "thank you", "application has been", "successfully", "received your",
    "we received", "submitted", "thanks for applying",
]


def _field_key(page, el) -> str:
    parts = []
    for attr in ("name", "id", "placeholder", "aria-label"):
        try:
            v = el.get_attribute(attr)
        except Exception:
            v = None
        if v:
            parts.append(v)
    try:
        el_id = el.get_attribute("id")
        if el_id:
            lab = page.query_selector(f"label[for='{el_id}']")
            if lab:
                parts.append(lab.inner_text())
    except Exception:
        pass
    return " ".join(parts).lower()


def _is_required(el) -> bool:
    try:
        if el.get_attribute("required") is not None:
            return True
        if (el.get_attribute("aria-required") or "").lower() == "true":
            return True
    except Exception:
        pass
    return False


def _has_captcha(page) -> bool:
    for sel in CAPTCHA_SELECTORS:
        try:
            if page.query_selector(sel):
                return True
        except Exception:
            continue
    return False


def fill_form(page, profile: dict, cv_path: str | None, submit: bool) -> dict:
    """Fill (and optionally submit) the application form on `page`.

    Returns: {status, reason, filled: [keys], missing: [labels]}
    status in {"filled", "submitted", "needs_review"}.
    """
    result = {"status": "filled", "reason": "", "filled": [], "missing": []}
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    if _has_captcha(page):
        result.update(status="needs_review", reason="CAPTCHA present")
        return result

    values = profile_values(profile)

    # ---- text inputs & textareas -----------------------------------------
    try:
        text_els = page.query_selector_all(
            "input:not([type='hidden']):not([type='file']):not([type='submit'])"
            ":not([type='button']):not([type='checkbox']):not([type='radio']), "
            "textarea"
        )
    except Exception:
        text_els = []

    for el in text_els:
        try:
            if not el.is_visible():
                continue
        except Exception:
            continue
        key = _field_key(page, el)
        matched_value = None
        matched_name = None
        for value_key, needles in TEXT_FIELD_PATTERNS:
            if any(n in key for n in needles):
                matched_name = value_key
                matched_value = values.get(value_key, "")
                break
        if matched_name and matched_value:
            try:
                el.fill(matched_value)
                result["filled"].append(matched_name)
            except Exception:
                pass
        elif _is_required(el) and not matched_name:
            # Required field we don't recognize (often a free-text question).
            label = key.strip()[:80] or "unknown required field"
            result["missing"].append(label)

    # ---- resume / CV upload ----------------------------------------------
    if cv_path:
        try:
            file_inputs = page.query_selector_all("input[type='file']")
            for fi in file_inputs:
                key = _field_key(page, fi)
                if any(w in key for w in ("resume", "cv", "attach", "file")) \
                        or len(file_inputs) == 1:
                    fi.set_input_files(cv_path)
                    result["filled"].append("resume")
                    break
        except Exception:
            pass

    # ---- native <select> screening questions -----------------------------
    try:
        selects = page.query_selector_all("select")
    except Exception:
        selects = []
    for sel in selects:
        try:
            if not sel.is_visible():
                continue
        except Exception:
            continue
        question = _field_key(page, sel)
        answer = known_question_answer(question, profile)
        if answer:
            try:
                sel.select_option(label=answer)
                result["filled"].append("question")
                continue
            except Exception:
                pass
        if _is_required(sel):
            result["missing"].append((question.strip()[:80]) or "required question")

    # ---- decide ----------------------------------------------------------
    if result["missing"]:
        result.update(status="needs_review",
                      reason="needs answers: " + "; ".join(result["missing"][:3]))
        return result

    if not submit:
        result.update(status="filled", reason="dry run (filled, not submitted)")
        return result

    # ---- submit ----------------------------------------------------------
    clicked = False
    for sel in SUBMIT_SELECTORS:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        result.update(status="needs_review", reason="no submit button found")
        return result

    try:
        page.wait_for_timeout(4000)
        body = (page.inner_text("body") or "").lower()
    except Exception:
        body = ""
    if any(t in body for t in CONFIRMATION_TEXTS):
        result.update(status="submitted", reason="confirmation detected")
    else:
        result.update(status="needs_review",
                      reason="submitted but no confirmation detected")
    return result
