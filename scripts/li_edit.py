"""Generalized Headline + About editor for ANY person (isolated profile dir).

Usage: python scripts/li_edit.py <slug> <headline_file> <about_file> [section]
  section: both | headline | about   (default both)

Handles empty About (new profile) via a largest-editable fallback, and locates
the headline as the sole editable on the intro edit page. Hebrew UI: Save='שמירה'.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SHOTS = ROOT / "data" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
SAVE_WORDS = ("שמירה", "save")
_BIDI = "".join(chr(c) for c in (0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e))


def _norm(s):
    return (s or "").translate({ord(c): None for c in _BIDI}).strip().lower()


def _is_save(b):
    try:
        al = _norm(b.get_attribute("aria-label"))
        txt = _norm(b.inner_text())
    except Exception:
        return False
    return "שמיר" in al or "שמיר" in txt or "save" in al or "save" in txt


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / name), full_page=False)
    except Exception:
        pass


def el_text(e):
    try:
        return e.input_value()
    except Exception:
        try:
            return e.inner_text() or ""
        except Exception:
            return ""


def _visible(e):
    try:
        return e.is_visible()
    except Exception:
        return False


def editables(page):
    return [e for e in page.query_selector_all("textarea, div[contenteditable='true']")
            if _visible(e)]


def set_field(page, e, text):
    tag = e.evaluate("el => el.tagName")
    e.click()
    page.wait_for_timeout(300)
    if tag == "TEXTAREA":
        try:
            e.fill(text)
            return
        except Exception:
            pass
    page.keyboard.press("Meta+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(200)
    page.keyboard.type(text)
    # Make React register the change (contenteditable/textarea).
    try:
        e.evaluate("el => el.dispatchEvent(new Event('input', {bubbles:true}))")
    except Exception:
        pass


def click_save(page):
    for b in page.query_selector_all("button"):
        try:
            if _is_save(b) and b.is_visible() and b.is_enabled():
                b.click()
                return True
        except Exception:
            continue
    return False


def _save_dialog(page):
    """Click the Save button INSIDE the open dialog; return True if it closed."""
    dlg = page.query_selector("div[role='dialog']")
    if not dlg:
        return False
    btn = None
    for b in dlg.query_selector_all("button"):
        try:
            if _is_save(b) and b.is_visible() and b.is_enabled():
                btn = b
                break
        except Exception:
            continue
    if not btn:
        return False
    btn.click()
    for _ in range(8):
        page.wait_for_timeout(500)
        d = page.query_selector("div[role='dialog']")
        if not d or not _visible(d):
            return True
    return False


def set_industry_if_empty(page, query="Software Development"):
    """The intro modal requires an Industry. Fill it (typeahead) if empty."""
    inp = None
    for i in page.query_selector_all("input"):
        al = _norm(i.get_attribute("aria-label"))
        ph = _norm(i.get_attribute("placeholder"))
        idv = _norm(i.get_attribute("id"))
        if "תעשי" in al or "industr" in al or "תעשי" in ph or "industr" in idv:
            inp = i
            break
    if not inp:
        for l in page.query_selector_all("label"):
            if "תעשי" in _norm(l.inner_text()):
                fid = l.get_attribute("for")
                if fid:
                    inp = page.query_selector(f"#{fid}")
                break
    if not inp:
        return "industry field not found"
    try:
        if (inp.input_value() or "").strip():
            return "industry already set"
    except Exception:
        pass
    try:
        inp.click()
        page.keyboard.press("Meta+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(300)
        inp.type(query)
        page.wait_for_timeout(1700)
        opts = [o for o in page.query_selector_all("[role='option'], .basic-typeahead__selectable")
                if _visible(o)]
        if opts:
            opts[0].click()
            page.wait_for_timeout(400)
            return f"industry set to {query}"
    except Exception as e:
        return f"industry error: {e}"[:80]
    return "no industry options"


def profile_slug(page):
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(5)
    for a in page.query_selector_all("a[href*='/edit/intro/'], a[href*='/edit/forms/']"):
        href = a.get_attribute("href") or ""
        if "/in/" in href:
            slug = href.split("/in/")[1].split("/")[0]
            if slug and slug != "me":
                return slug
    try:
        return page.url.split("/in/")[1].split("/")[0]
    except Exception:
        return "me"


def edit_headline(page, slug, text):
    page.goto(f"https://www.linkedin.com/in/{slug}/edit/intro/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    shot(page, "shani_intro_edit.png")
    eds = editables(page)
    # Prefer an editable that looks like the current headline; else the sole one.
    field = None
    for e in eds:
        t = el_text(e).lower()
        if "student" in t or "holon" in t or "computer science" in t:
            field = e
            break
    if not field and len(eds) == 1:
        field = eds[0]
    if not field:
        return {"section": "headline", "ok": False,
                "reason": f"ambiguous ({len(eds)} editables)"}
    set_field(page, field, text)
    page.wait_for_timeout(600)
    # The intro modal requires an Industry — fill it or Save is rejected.
    ind = set_industry_if_empty(page)
    print(f"  industry: {ind}", flush=True)
    shot(page, "shani_headline_typed.png")
    # Scope Save to the open dialog and confirm the dialog actually closes.
    saved = _save_dialog(page)
    if not saved:
        if not click_save(page):
            return {"section": "headline", "ok": False, "reason": "save button not found"}
    time.sleep(4)
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    ok = text[:40] in (page.inner_text("body") or "")
    shot(page, "shani_headline_after.png")
    return {"section": "headline", "ok": ok,
            "reason": "verified on profile" if ok else "saved; not verified"}


def edit_about(page, slug, text):
    page.goto(f"https://www.linkedin.com/in/{slug}/edit/forms/summary/new/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    shot(page, "shani_about_edit.png")
    eds = sorted(editables(page), key=lambda e: len(el_text(e)), reverse=True)
    field = eds[0] if eds else None
    if not field:
        return {"section": "about", "ok": False, "reason": "About field not found"}
    set_field(page, field, text)
    page.wait_for_timeout(600)
    shot(page, "shani_about_typed.png")
    if not click_save(page):
        return {"section": "about", "ok": False, "reason": "save button not found"}
    time.sleep(4)
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    ok = text[:40].lower() in (page.inner_text("body") or "").lower()
    shot(page, "shani_about_after.png")
    return {"section": "about", "ok": ok,
            "reason": "verified on profile" if ok else "saved; not verified"}


def main(slug, headline_file, about_file, section):
    headline = Path(headline_file).read_text(encoding="utf-8").strip()
    about = Path(about_file).read_text(encoding="utf-8").strip()
    profile_dir = ROOT / "data" / "li_profiles" / slug
    results = []
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        real_slug = profile_slug(page)
        if "/login" in page.url.lower() or "/authwall" in page.url.lower():
            print("RESULT NOT_LOGGED_IN")
            ctx.close()
            return 1
        print(f"slug={real_slug}", flush=True)
        if section in ("both", "headline"):
            try:
                results.append(edit_headline(page, real_slug, headline))
            except Exception as e:
                results.append({"section": "headline", "ok": False, "reason": str(e)[:90]})
        if section in ("both", "about"):
            try:
                results.append(edit_about(page, real_slug, about))
            except Exception as e:
                results.append({"section": "about", "ok": False, "reason": str(e)[:90]})
        time.sleep(1.5)
        ctx.close()
    for r in results:
        print(f"RESULT {r['section']}: ok={r['ok']} :: {r['reason']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: li_edit.py <slug> <headline_file> <about_file> [section]")
        raise SystemExit(2)
    sec = sys.argv[4] if len(sys.argv) > 4 else "both"
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3], sec))
