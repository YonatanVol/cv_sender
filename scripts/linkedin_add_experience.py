"""Add the BuzzTech experience entry to the logged-in LinkedIn profile.

Uses the direct Add-experience form (/edit/forms/position/new/). Handles the
Hebrew UI and the company-name autocomplete conservatively: it only clicks a
suggestion that is an EXACT case-insensitive match for the company, otherwise
it keeps the typed free-text (so we never attach the wrong company entity).

Verifies afterward by reloading the profile. Screenshots each step.

Usage:  python scripts/linkedin_add_experience.py <desc_file>
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SHOTS = ROOT / "data" / "screenshots"

PROFILE_SLUG = "yonatanvolsky"
TITLE = "Customer Success & Data Automation Developer"
COMPANY = "BuzzTech"
LOCATION = "Tel Aviv-Yafo, Israel"
START_YEAR = "2025"


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / name), full_page=False)
    except Exception:
        pass


def by_placeholder(page, needle):
    for e in page.query_selector_all("input"):
        ph = e.get_attribute("placeholder") or ""
        if needle.lower() in ph.lower() and e.is_visible():
            return e
    return None


def select_by_label(page, label_needle):
    for s in page.query_selector_all("select"):
        eid = s.get_attribute("id") or ""
        lab = ""
        if eid:
            l = page.query_selector(f"label[for='{eid}']")
            if l:
                lab = l.inner_text() or ""
        if label_needle in lab and s.is_visible():
            return s
    return None


def fill_company(page, inp):
    inp.click()
    inp.fill(COMPANY)
    time.sleep(2.5)
    # look for an exact-match suggestion
    opts = page.query_selector_all(
        "[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li")
    for o in opts:
        try:
            txt = (o.inner_text() or "").strip().lower()
            if txt.split("\n")[0].strip() == COMPANY.lower():
                o.click()
                return "selected exact suggestion"
        except Exception:
            continue
    # no exact match: keep typed free-text
    page.keyboard.press("Escape")
    return "kept free text"


def set_description(page, text):
    field = None
    for e in page.query_selector_all("div[contenteditable='true']"):
        al = (e.get_attribute("aria-label") or "")
        if "תיאור" in al or "description" in al.lower():
            field = e
            break
    if not field:
        return False
    field.click()
    time.sleep(0.3)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        page.keyboard.type(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")
    return True


def click_save(page):
    for b in page.query_selector_all("button"):
        t = (b.inner_text() or "").strip()
        al = (b.get_attribute("aria-label") or "")
        if t == "שמירה" or "שמירה" in al:
            if b.is_visible() and b.is_enabled():
                b.click()
                return True
    return False


def main(desc_file):
    desc = Path(desc_file).read_text(encoding="utf-8").strip()
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://www.linkedin.com/in/{PROFILE_SLUG}/edit/forms/position/new/",
                  wait_until="domcontentloaded", timeout=45000)
        time.sleep(7)

        title = by_placeholder(page, "מנהל")
        company = by_placeholder(page, "Microsoft")
        location = by_placeholder(page, "לונדון")
        if not (title and company):
            shot(page, "li_exp_notfound.png")
            print(f"RESULT ok=False :: title/company field not found "
                  f"(url={page.url}, inputs={len(page.query_selector_all('input'))})")
            ctx.close()
            return 1
        title.click(); title.fill(TITLE)
        comp_note = fill_company(page, company)
        if location:
            location.click(); location.fill(LOCATION)
        yr = select_by_label(page, "שנה")
        year_note = "no year select"
        if yr:
            try:
                yr.select_option(label=START_YEAR)
                year_note = f"year={START_YEAR}"
            except Exception as e:
                year_note = f"year err: {e}"[:50]
        desc_ok = set_description(page, desc)
        time.sleep(0.5)
        shot(page, "li_exp_before_save.png")
        # read back company value for safety
        comp_val = ""
        try:
            comp_val = company.input_value()
        except Exception:
            pass
        saved = click_save(page)
        time.sleep(4)
        page.goto("https://www.linkedin.com/in/me/",
                  wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        body = (page.inner_text("body") or "")
        ok = "BuzzTech" in body and "Data Automation" in body
        shot(page, "li_exp_after.png")
        print(f"RESULT ok={ok} :: company[{comp_note}, value={comp_val!r}] "
              f"{year_note} desc={desc_ok} saved={saved}")
        ctx.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
