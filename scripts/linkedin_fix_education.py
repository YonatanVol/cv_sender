"""Change the main Education entry's school to HIT (Holon Institute of Technology).

Edits the existing entry in place (keeps degree, field of study and dates).
Only the School autocomplete is touched. Verifies via the education details page.

Usage:  python scripts/linkedin_fix_education.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SHOTS = ROOT / "data" / "screenshots"
EDIT_URL = ("https://www.linkedin.com/in/yonatanvolsky/"
            "details/education/edit/forms/935017040/")
DETAILS_URL = "https://www.linkedin.com/in/yonatanvolsky/details/education/"
SCHOOL_QUERY = "Holon Institute of Technology"
MATCH = "holon institute"


def main():
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)

        # School field = input currently holding the old school name.
        school = None
        for e in page.query_selector_all("input"):
            try:
                v = e.input_value()
            except Exception:
                v = ""
            if e.is_visible() and ("open university" in v.lower()
                                   or "בוסטון" in (e.get_attribute("placeholder") or "")):
                school = e
                break
        if not school:
            print("RESULT ok=False :: school field not found")
            ctx.close()
            return 1

        school.click()
        school.fill("")
        time.sleep(0.4)
        school.type(SCHOOL_QUERY, delay=40)
        time.sleep(2.5)
        note = "kept free text"
        for o in page.query_selector_all(
                "[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li"):
            try:
                txt = (o.inner_text() or "").lower()
                if MATCH in txt:
                    o.click()
                    note = "selected suggestion"
                    break
            except Exception:
                continue
        else:
            page.keyboard.press("Escape")
        time.sleep(0.6)
        try:
            new_val = school.input_value()
        except Exception:
            new_val = "?"
        try:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "li_edu_before_save.png"))
        except Exception:
            pass

        saved = False
        for b in page.query_selector_all("button"):
            if (b.inner_text() or "").strip() == "שמירה" and b.is_visible() and b.is_enabled():
                b.click()
                saved = True
                break
        time.sleep(4)

        page.goto(DETAILS_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        body = (page.inner_text("main") or "")
        ok = "Holon Institute" in body
        try:
            page.screenshot(path=str(SHOTS / "li_edu_after.png"))
        except Exception:
            pass
        print(f"RESULT ok={ok} :: {note}, field now={new_val!r}, saved={saved}")
        ctx.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
