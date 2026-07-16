"""Add education entries for ANY person (isolated profile dir), from a JSON list.

Usage: python scripts/li_add_education.py <profile_slug> <url_slug> <education_json>

Fresh context per entry -> /edit/forms/education/new/ -> school (typeahead),
degree, field of study, start/end year -> Save. Hebrew UI.
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


def by_placeholder(page, needle):
    for e in page.query_selector_all("input"):
        if e.is_visible() and needle.lower() in (e.get_attribute("placeholder") or "").lower():
            return e
    return None


def by_aria(page, needle, avoid=None):
    for e in page.query_selector_all("input"):
        al = e.get_attribute("aria-label") or ""
        if e.is_visible() and needle in al and (not avoid or avoid not in al):
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
        if "שנה" in lab or "Year" in lab:
            out.append(s)
    return out


def fill_typeahead(page, inp, value):
    inp.click()
    inp.fill(value)
    time.sleep(2.5)
    for o in page.query_selector_all("[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li"):
        try:
            first = (o.inner_text() or "").strip().split("\n")[0].strip().lower()
            if first == value.lower():
                o.click()
                return "exact"
        except Exception:
            continue
    page.keyboard.press("Escape")
    return "free text"


def set_year(sel, year):
    try:
        sel.select_option(label=year)
        return True
    except Exception:
        try:
            sel.select_option(value=year)
            return True
        except Exception:
            return False


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


def add_one(page, url_slug, edu):
    page.goto(f"https://www.linkedin.com/in/{url_slug}/edit/forms/education/new/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(7)
    school = by_placeholder(page, "אוניברסיטת")
    if not school:
        return {"school": edu["school"], "ok": False, "reason": "school field not found"}
    snote = fill_typeahead(page, school, edu["school"])
    degree = by_aria(page, "תואר")
    if degree and edu.get("degree"):
        degree.click(); degree.fill(edu["degree"])
    field = by_aria(page, "תחום")
    if field and edu.get("field"):
        field.click(); field.fill(edu["field"])
    # uncheck "currently studying" if present, so end year applies
    for c in page.query_selector_all("input[type='checkbox']"):
        if c.is_checked():
            c.evaluate("el=>el.click()")
            time.sleep(1)
            break
    ys = year_selects(page)
    if ys:
        set_year(ys[0], edu["start_year"])
    if edu.get("end_year") and len(ys) >= 2:
        set_year(ys[-1], edu["end_year"])
    time.sleep(0.4)
    saved = _save(page)
    time.sleep(4)
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    ok = edu["school"].lower() in (page.inner_text("body") or "").lower()
    return {"school": edu["school"], "school_match": snote, "saved": saved, "verified": ok}


def main(profile_slug, url_slug, education_json):
    edus = json.loads(Path(education_json).read_text(encoding="utf-8"))
    profile_dir = ROOT / "data" / "li_profiles" / profile_slug
    results = []
    for edu in edus:
        with sync_playwright() as p:
            ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                results.append(add_one(page, url_slug, edu))
            except Exception as e:
                results.append({"school": edu["school"], "ok": False, "reason": str(e)[:70]})
            ctx.close()
        time.sleep(2)
    for r in results:
        print(f"RESULT {r}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: li_add_education.py <profile_slug> <url_slug> <education_json>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
