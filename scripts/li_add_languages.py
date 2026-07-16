"""Add languages for ANY person (isolated profile dir), from a JSON list.

Usage: python scripts/li_add_languages.py <profile_slug> <url_slug> <languages_json>

Each language: fresh context -> /edit/forms/language/new/ -> type language name
(pick suggestion) -> choose proficiency (select by value) -> Save. Hebrew UI.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

_BIDI = "".join(chr(c) for c in (0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e))


def _norm(s):
    return (s or "").translate({ord(c): None for c in _BIDI}).strip().lower()


def _save(page):
    for b in page.query_selector_all("button"):
        try:
            al = _norm(b.get_attribute("aria-label"))
            tx = _norm(b.inner_text())
            if ("שמיר" in al or "שמיר" in tx or "save" in al or "save" in tx) \
                    and b.is_visible() and b.is_enabled():
                b.click()
                return True
        except Exception:
            continue
    return False


def add_one(page, url_slug, lang):
    page.goto(f"https://www.linkedin.com/in/{url_slug}/edit/forms/language/new/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    # language name input: aria-label contains 'שפה' (not the 'חיפוש' search box)
    name_inp = None
    for i in page.query_selector_all("input"):
        al = i.get_attribute("aria-label") or ""
        if "שפה" in al and i.is_visible():
            name_inp = i
            break
    if not name_inp:
        return {"lang": lang["name"], "ok": False, "reason": "name input not found"}
    name_inp.click()
    name_inp.fill(lang["name"])
    time.sleep(1.5)
    opts = [o for o in page.query_selector_all("[role='option'], .basic-typeahead__selectable")
            if o.is_visible()]
    for o in opts:
        if _norm(o.inner_text()).startswith(lang["name"].lower()):
            o.click()
            break
    # proficiency select (the one whose options are LanguageProficiency_*)
    prof_sel = None
    for s in page.query_selector_all("select"):
        vals = [o.get_attribute("value") or "" for o in s.query_selector_all("option")]
        if any(v.startswith("LanguageProficiency_") for v in vals):
            prof_sel = s
            break
    if prof_sel:
        try:
            prof_sel.select_option(value=lang["proficiency"])
        except Exception:
            pass
    time.sleep(0.4)
    saved = _save(page)
    time.sleep(3)
    return {"lang": lang["name"], "saved": saved}


def main(profile_slug, url_slug, languages_json):
    langs = json.loads(Path(languages_json).read_text(encoding="utf-8"))
    profile_dir = ROOT / "data" / "li_profiles" / profile_slug
    results = []
    for lang in langs:
        with sync_playwright() as p:
            ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                results.append(add_one(page, url_slug, lang))
            except Exception as e:
                results.append({"lang": lang["name"], "ok": False, "reason": str(e)[:70]})
            ctx.close()
        time.sleep(2)
    for r in results:
        print(f"RESULT {r}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: li_add_languages.py <profile_slug> <url_slug> <languages_json>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
