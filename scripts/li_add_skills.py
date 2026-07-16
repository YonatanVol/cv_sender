"""Add skills for ANY person (isolated profile dir), from a JSON list.

Usage: python scripts/li_add_skills.py <profile_slug> <url_slug> <skills_json> [index]

Each skill: open /skills/edit/forms/new/, type the name, pick the matching
suggestion, Save (Hebrew 'שמירה'). Hebrew UI; robust bidi-safe Save match.
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


def skill_input(page):
    for i in page.query_selector_all("input"):
        if not i.is_visible():
            continue
        ph = i.get_attribute("placeholder") or ""
        al = i.get_attribute("aria-label") or ""
        if "מיומנות" in ph or "מיומנות" in al:
            return i
    return None


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


def add_skill(page, new_url, details_url, query):
    inp = None
    for attempt in range(2):
        if attempt == 1:
            page.goto(details_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
        page.goto(new_url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)
        inp = skill_input(page)
        if inp:
            break
    if not inp:
        return {"skill": query, "ok": False, "reason": "input not found"}
    inp.click()
    inp.fill(query)
    time.sleep(2.5)
    opts = page.query_selector_all(
        "[role='option'], .basic-typeahead__selectable, ul[role='listbox'] li")
    chosen = None
    for o in opts:
        first = (o.inner_text() or "").strip().split("\n")[0].strip()
        if first.lower() == query.lower():
            o.click(); chosen = first; break
    if not chosen:
        for o in opts:
            first = (o.inner_text() or "").strip().split("\n")[0].strip()
            if first.lower().startswith(query.split(" (")[0].lower()):
                o.click(); chosen = first; break
    if not chosen and opts:
        chosen = (opts[0].inner_text() or "").split("\n")[0]
        opts[0].click()
    if not chosen:
        return {"skill": query, "ok": False, "reason": "no suggestion"}
    time.sleep(0.5)
    saved = _save(page)
    time.sleep(3)
    return {"skill": query, "chosen": chosen, "saved": saved}


def main(profile_slug, url_slug, skills_json, index):
    skills = json.loads(Path(skills_json).read_text(encoding="utf-8"))
    todo = [skills[index]] if index is not None else skills
    new_url = f"https://www.linkedin.com/in/{url_slug}/skills/edit/forms/new/"
    details = f"https://www.linkedin.com/in/{url_slug}/details/skills/"
    profile_dir = ROOT / "data" / "li_profiles" / profile_slug
    results = []
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for s in todo:
            try:
                results.append(add_skill(page, new_url, details, s))
            except Exception as e:
                results.append({"skill": s, "ok": False, "reason": str(e)[:70]})
        ctx.close()
    ok = sum(1 for r in results if r.get("saved"))
    for r in results:
        print(f"RESULT {r}")
    print(f"SUMMARY saved {ok}/{len(results)}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: li_add_skills.py <profile_slug> <url_slug> <skills_json> [index]")
        raise SystemExit(2)
    idx = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else None
    main(sys.argv[1], sys.argv[2], sys.argv[3], idx)
