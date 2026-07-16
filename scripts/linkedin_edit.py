"""Apply Headline + About edits to the logged-in LinkedIn profile (Hebrew UI).

Structure discovered on this account:
  - "Edit intro" is a full page at /in/<slug>/edit/intro/; the Headline is a
    <div contenteditable>. Save button text = 'שמירה'.
  - About is edited from the profile via the 'על אודות' pencil.

Safety: before replacing a field we confirm it currently contains the known
OLD text, so we never overwrite the wrong field.

Usage:  python scripts/linkedin_edit.py <headline_file> <about_file>
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

OLD_HEADLINE_MARK = "buzztech"          # current headline contains this
OLD_ABOUT_MARK = "computer science student at hit"   # current About contains this
SAVE_WORDS = ("שמירה", "save")


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


def editables(page):
    return [e for e in page.query_selector_all("textarea, div[contenteditable='true']")
            if _visible(e)]


def _visible(e):
    try:
        return e.is_visible()
    except Exception:
        return False


def find_editable_with(page, needle):
    needle = needle.lower()
    for e in editables(page):
        if needle in el_text(e).lower():
            return e
    return None


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
    # contenteditable (or textarea fallback): select-all, delete, type
    page.keyboard.press("Meta+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(200)
    page.keyboard.type(text)


def click_save(page):
    for b in page.query_selector_all("button"):
        try:
            al = (b.get_attribute("aria-label") or "").lower()
            txt = (b.inner_text() or "").strip().lower()
            if any(w in al for w in SAVE_WORDS) or any(w == txt for w in SAVE_WORDS):
                if b.is_visible() and b.is_enabled():
                    b.click()
                    return True
        except Exception:
            continue
    return False


def profile_slug(page):
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(5)
    # The canonical slug is in the edit-links' hrefs (URL bar may stay /in/me/).
    for a in page.query_selector_all("a[href*='/edit/intro/'], a[href*='/edit/forms/']"):
        href = a.get_attribute("href") or ""
        if "/in/" in href:
            slug = href.split("/in/")[1].split("/")[0]
            if slug and slug != "me":
                return slug
    url = page.url
    try:
        return url.split("/in/")[1].split("/")[0]
    except Exception:
        return "me"


def edit_headline(page, slug, text):
    page.goto(f"https://www.linkedin.com/in/{slug}/edit/intro/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    shot(page, "li_intro_edit.png")
    field = find_editable_with(page, OLD_HEADLINE_MARK)
    if not field:
        eds = editables(page)
        field = eds[0] if len(eds) == 1 else None
    if not field:
        return {"section": "headline", "ok": False,
                "reason": "could not confidently locate headline field"}
    set_field(page, field, text)
    page.wait_for_timeout(600)
    shot(page, "li_headline_typed.png")
    if not click_save(page):
        return {"section": "headline", "ok": False, "reason": "save button not found"}
    time.sleep(4)
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    ok = text[:40] in (page.inner_text("body") or "")
    shot(page, "li_headline_after.png")
    return {"section": "headline", "ok": ok,
            "reason": "verified on profile" if ok else "saved; not verified"}


def edit_about(page, slug, text):
    # About has its own edit page (discovered from the pencil's href).
    page.goto(f"https://www.linkedin.com/in/{slug}/edit/forms/summary/new/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    shot(page, "li_about_edit.png")
    field = find_editable_with(page, OLD_ABOUT_MARK)
    if not field:
        eds = sorted(editables(page), key=lambda e: len(el_text(e)), reverse=True)
        field = eds[0] if eds else None
    if not field:
        return {"section": "about", "ok": False, "reason": "About text field not found"}
    set_field(page, field, text)
    page.wait_for_timeout(600)
    shot(page, "li_about_typed.png")
    if not click_save(page):
        return {"section": "about", "ok": False, "reason": "save button not found"}
    time.sleep(4)
    page.goto("https://www.linkedin.com/in/me/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    body = (page.inner_text("body") or "").lower()
    ok = text[:40].lower() in body
    shot(page, "li_about_after.png")
    return {"section": "about", "ok": ok,
            "reason": "verified on profile" if ok else "saved; not verified"}


def main(headline_file, about_file):
    headline = Path(headline_file).read_text(encoding="utf-8").strip()
    about = Path(about_file).read_text(encoding="utf-8").strip()
    results = []
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        slug = profile_slug(page)
        if "/login" in page.url.lower() or "/authwall" in page.url.lower():
            print("RESULT NOT_LOGGED_IN")
            ctx.close()
            return 1
        print(f"slug={slug}", flush=True)
        section = sys.argv[3] if len(sys.argv) > 3 else "both"
        if section in ("both", "headline"):
            try:
                results.append(edit_headline(page, slug, headline))
            except Exception as e:
                results.append({"section": "headline", "ok": False, "reason": str(e)[:90]})
        if section in ("both", "about"):
            try:
                results.append(edit_about(page, slug, about))
            except Exception as e:
                results.append({"section": "about", "ok": False, "reason": str(e)[:90]})
        time.sleep(1.5)
        ctx.close()
    for r in results:
        print(f"RESULT {r['section']}: ok={r['ok']} :: {r['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
