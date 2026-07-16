"""Fix the BuzzTech experience company name to the correct spelling 'Buzzztech'.

LinkedIn auto-matched a different entity ('Buzztech', two z's) when the entry
was created. This clears the company field and re-enters 'Buzzztech', selecting
an exact 3-z suggestion if present, otherwise keeping the typed free text.

Usage:  python scripts/linkedin_fix_company.py
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
            "details/experience/edit/forms/2954795322/")
DETAILS = "https://www.linkedin.com/in/yonatanvolsky/details/experience/"
CORRECT = "Buzzztech"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)

        company = None
        for e in page.query_selector_all("input"):
            if not e.is_visible():
                continue
            try:
                v = e.input_value()
            except Exception:
                v = ""
            ph = e.get_attribute("placeholder") or ""
            if "buzz" in v.lower() or "Microsoft" in ph:
                company = e
                break
        if not company:
            print("RESULT ok=False :: company field not found")
            ctx.close()
            return 1

        company.click()
        company.fill("")
        time.sleep(0.4)
        company.type(CORRECT, delay=60)
        time.sleep(2.5)
        note = "kept free text"
        for o in page.query_selector_all(
                "[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li"):
            try:
                first = (o.inner_text() or "").strip().split("\n")[0].strip().lower()
                if first == CORRECT.lower():
                    o.click()
                    note = "selected exact 3-z suggestion"
                    break
            except Exception:
                continue
        else:
            page.keyboard.press("Escape")
        time.sleep(0.5)
        try:
            val = company.input_value()
        except Exception:
            val = "?"
        page.screenshot(path=str(SHOTS / "li_company_before_save.png"))

        saved = False
        for b in page.query_selector_all("button"):
            if (b.inner_text() or "").strip() == "שמירה" and b.is_visible() and b.is_enabled():
                b.click()
                saved = True
                break
        time.sleep(4)

        page.goto(DETAILS, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        body = page.inner_text("main") or ""
        ok = CORRECT in body
        page.screenshot(path=str(SHOTS / "li_company_after.png"))
        print(f"RESULT ok={ok} :: {note}, field now={val!r}, saved={saved}")
        ctx.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
