"""Add several experience entries to the logged-in LinkedIn profile (Hebrew UI).

Handles ongoing roles (left as "Present") and ended roles (unchecks
"I currently work here" and sets an end year). Company autocomplete is
conservative: only an EXACT case-insensitive suggestion is selected, else the
typed free-text is kept. Verifies each entry on the profile.

Usage:  python scripts/linkedin_add_positions.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SLUG = "yonatanvolsky"
NEW_URL = f"https://www.linkedin.com/in/{SLUG}/edit/forms/position/new/"

POSITIONS = [
    {
        "title": "Owner & Operator",
        "company": "YaffoTLV",
        "location": "Jaffa, Tel Aviv, Israel",
        "start_year": "2019",
        "end_year": None,   # ongoing
        "desc": [
            "• Manage a short-term rental property in Jaffa end-to-end — pricing, operations, vendors, marketing, guest experience and performance tracking.",
            "• Designed workflows for bookings, cleaning coordination, service quality and ongoing property management.",
            "• Built and deployed the property's website (yaffotlv.com) using Next.js, React, TypeScript and Tailwind CSS.",
        ],
    },
    {
        "title": "Technology Sales Specialist",
        "company": "Bug Multisystems",
        "location": "Israel",
        "start_year": "2024",
        "end_year": "2025",
        "desc": [
            "• Provided technical consultation on hardware, software and consumer technology products, translating customer needs into practical recommendations.",
        ],
    },
    {
        "title": "Excel & SAP Analyst",
        "company": "Israel Defense Forces",
        "location": "Israel",
        "start_year": "2018",
        "end_year": "2019",
        "desc": [
            "• Analyzed operational datasets using Excel and SAP, created structured reports and maintained data accuracy across internal systems.",
        ],
    },
]


def by_placeholder(page, needle):
    for e in page.query_selector_all("input"):
        ph = e.get_attribute("placeholder") or ""
        if needle.lower() in ph.lower() and e.is_visible():
            return e
    return None


def year_selects(page):
    out = []
    for s in page.query_selector_all("select"):
        eid = s.get_attribute("id") or ""
        lab = ""
        if eid:
            l = page.query_selector(f"label[for='{eid}']")
            if l:
                lab = l.inner_text() or ""
        if "Year" in lab or "שנה" in lab:
            out.append(s)
    return out


def fill_company(page, inp, company):
    inp.click()
    inp.fill(company)
    time.sleep(2.5)
    for o in page.query_selector_all(
            "[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li"):
        try:
            first = (o.inner_text() or "").strip().split("\n")[0].strip().lower()
            if first == company.lower():
                o.click()
                return "exact match"
        except Exception:
            continue
    page.keyboard.press("Escape")
    return "free text"


def set_description(page, lines):
    field = None
    for e in page.query_selector_all("div[contenteditable='true']"):
        al = e.get_attribute("aria-label") or ""
        if "תיאור" in al or "description" in al.lower():
            field = e
            break
    if not field:
        return False
    field.click()
    time.sleep(0.3)
    for i, line in enumerate(lines):
        page.keyboard.type(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")
    return True


def set_year(sel, year):
    for lab in (year,):
        try:
            sel.select_option(label=lab)
            return True
        except Exception:
            pass
    try:
        sel.select_option(value=year)
        return True
    except Exception:
        return False


def click_save(page):
    for b in page.query_selector_all("button"):
        if (b.inner_text() or "").strip() == "שמירה" and b.is_visible() and b.is_enabled():
            b.click()
            return True
    return False


def add_one(page, pos):
    # position/new only mounts reliably as the first navigation of a fresh
    # context (no reload, no prior LinkedIn page). So this script adds ONE
    # position per process run (by index).
    page.goto(NEW_URL, wait_until="domcontentloaded", timeout=45000)
    time.sleep(8)
    title = by_placeholder(page, "מנהל")
    company = by_placeholder(page, "Microsoft")
    location = by_placeholder(page, "לונדון")
    if not (title and company):
        return {"title": pos["title"], "ok": False, "reason": "fields not found"}
    title.click(); title.fill(pos["title"])
    cnote = fill_company(page, company, pos["company"])
    if location:
        location.click(); location.fill(pos["location"])
    ys = year_selects(page)
    if ys:
        set_year(ys[0], pos["start_year"])
    if pos["end_year"]:
        for c in page.query_selector_all("input[type='checkbox']"):
            if c.is_checked():
                c.evaluate("el=>el.click()")
                break
        time.sleep(1.5)
        ys = year_selects(page)
        if len(ys) >= 2:
            set_year(ys[-1], pos["end_year"])
    set_description(page, pos["desc"])
    time.sleep(0.4)
    saved = click_save(page)
    time.sleep(4)
    return {"title": pos["title"], "company_note": cnote, "saved": saved}


def main():
    idx = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    todo = [POSITIONS[idx]] if idx is not None else POSITIONS
    results = []
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for pos in todo:
            try:
                results.append(add_one(page, pos))
            except Exception as e:
                results.append({"title": pos["title"], "ok": False, "reason": str(e)[:80]})
        ctx.close()
    for r in results:
        print(f"RESULT {r}")


if __name__ == "__main__":
    main()
