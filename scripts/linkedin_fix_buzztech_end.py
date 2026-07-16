"""Set an end date (March 2026) on the BuzzTech experience entry.

Unchecks "I currently work here" (via a JS click so React registers it), which
reveals the end month/year selects, then sets March 2026 and saves. Verifies
on the experience details page.

Usage:  python scripts/linkedin_fix_buzztech_end.py
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


def label_of(page, s):
    eid = s.get_attribute("id") or ""
    if eid:
        l = page.query_selector(f"label[for='{eid}']")
        if l:
            return l.inner_text() or ""
    return ""


def selects_by(page, words):
    out = []
    for s in page.query_selector_all("select"):
        lab = label_of(page, s)
        if any(w in lab for w in words):
            out.append(s)
    return out


def set_select(s, labels, values):
    for lab in labels:
        try:
            s.select_option(label=lab)
            return True
        except Exception:
            pass
    for v in values:
        try:
            s.select_option(value=v)
            return True
        except Exception:
            pass
    return False


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)

        # target = checked checkbox that is NOT a skill (empty surrounding text)
        target = None
        for c in page.query_selector_all("input[type='checkbox']"):
            if not c.is_checked():
                continue
            ctxtxt = c.evaluate(
                "el=>{let p=el.closest('fieldset,label,li,div');"
                "return p?p.innerText.trim():''}")
            if ctxtxt == "":
                target = c
                break
        if not target:
            print("RESULT ok=False :: 'currently working' checkbox not found")
            ctx.close()
            return 1

        year_before = len(selects_by(page, ["Year", "שנה"]))
        target.evaluate("el=>el.click()")   # uncheck via React-friendly click
        time.sleep(2.5)
        year_after = len(selects_by(page, ["Year", "שנה"]))
        if year_after <= year_before:
            print(f"RESULT ok=False :: end-date fields did not appear "
                  f"(year selects {year_before}->{year_after})")
            ctx.close()
            return 1

        months = selects_by(page, ["Month", "חודש"])
        years = selects_by(page, ["Year", "שנה"])
        m_ok = set_select(months[-1], ["March", "מרץ", "Mar"], ["3", "03"])
        y_ok = set_select(years[-1], ["2026"], ["2026"])
        time.sleep(0.5)
        page.screenshot(path=str(SHOTS / "li_buzz_end_before_save.png"))

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
        # find the BuzzTech block and show its date line
        line = ""
        for chunk in body.split("\n"):
            if "2026" in chunk:
                line = chunk.strip()
        ok = "2026" in body and "Buzztech" in body
        page.screenshot(path=str(SHOTS / "li_buzz_end_after.png"))
        print(f"RESULT ok={ok} :: month={m_ok} year={y_ok} saved={saved} "
              f"date_line~={line!r}")
        ctx.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
