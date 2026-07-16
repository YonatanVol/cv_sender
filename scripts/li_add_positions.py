"""Add experience entries for ANY person (isolated profile dir), from a JSON spec.

Usage: python scripts/li_add_positions.py <slug> <positions_json> [index]

Each position is added in its OWN fresh browser context (the position/new form
only mounts reliably on the first navigation of a fresh context). Hebrew UI.
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
    try:
        sel.select_option(label=year)
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


def add_one(page, url_slug, pos):
    page.goto(f"https://www.linkedin.com/in/{url_slug}/edit/forms/position/new/",
              wait_until="domcontentloaded", timeout=45000)
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
    if pos.get("end_year"):
        # Uncheck all checked boxes: "currently working here" (reveals the
        # end-date fields) and the "update headline / share" box (protects the
        # new headline and avoids feed-spamming the network with old jobs).
        for _ in range(3):
            checked = [c for c in page.query_selector_all("input[type='checkbox']")
                       if c.is_checked()]
            if not checked:
                break
            checked[0].evaluate("el=>el.click()")
            time.sleep(1.0)
        ys = year_selects(page)
        if len(ys) >= 2:
            set_year(ys[-1], pos["end_year"])
    set_description(page, pos["desc"])
    time.sleep(0.4)
    saved = click_save(page)
    time.sleep(4)
    # verify
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    ok = pos["title"].lower() in (page.inner_text("body") or "").lower()
    return {"title": pos["title"], "company": cnote, "saved": saved, "verified": ok}


def main(profile_slug, url_slug, positions_json, index):
    positions = json.loads(Path(positions_json).read_text(encoding="utf-8"))
    todo = [positions[index]] if index is not None else positions
    profile_dir = ROOT / "data" / "li_profiles" / profile_slug
    results = []
    for pos in todo:
        with sync_playwright() as p:
            ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                results.append(add_one(page, url_slug, pos))
            except Exception as e:
                results.append({"title": pos["title"], "ok": False, "reason": str(e)[:80]})
            ctx.close()
        time.sleep(2)
    for r in results:
        print(f"RESULT {r}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: li_add_positions.py <profile_slug> <url_slug> <positions_json> [index]")
        raise SystemExit(2)
    idx = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else None
    main(sys.argv[1], sys.argv[2], sys.argv[3], idx)
