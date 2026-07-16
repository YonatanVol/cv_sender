"""Add software skills to the logged-in LinkedIn profile (Hebrew UI).

Each skill is its own form submission at /skills/edit/forms/new/ — type the
canonical skill name, pick the matching suggestion, Save (שמירה). Optionally
add only SKILLS[index] (one per process) if the multi-add navigation flakes.

Usage:  python scripts/linkedin_add_skills.py [index]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SLUG = "yonatanvolsky"
NEW_URL = f"https://www.linkedin.com/in/{SLUG}/skills/edit/forms/new/"
DETAILS = f"https://www.linkedin.com/in/{SLUG}/details/skills/"

SKILLS = [
    "Python (Programming Language)",
    "JavaScript",
    "TypeScript",
    "SQL",
    "Java",
    "C (Programming Language)",
    "React.js",
    "Next.js",
    "REST APIs",
    "MySQL",
    "Tailwind CSS",
    "Data Analysis",
    "Extract, Transform, Load (ETL)",
    "Git",
    "Object-Oriented Programming (OOP)",
    "Data Structures",
    "Algorithms",
    "Web Development",
    "Google Apps Script",
]


def skill_input(page):
    for i in page.query_selector_all("input"):
        if not i.is_visible():
            continue
        ph = i.get_attribute("placeholder") or ""
        al = i.get_attribute("aria-label") or ""
        if "מיומנות" in ph or "מיומנות" in al:
            return i
    return None


def add_skill(page, query):
    inp = None
    for attempt in range(2):
        if attempt == 1:
            page.goto(DETAILS, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
        page.goto(NEW_URL, wait_until="domcontentloaded", timeout=45000)
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
    # exact first-line match preferred
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
    saved = False
    for b in page.query_selector_all("button"):
        if (b.inner_text() or "").strip() == "שמירה" and b.is_visible() and b.is_enabled():
            b.click(); saved = True; break
    time.sleep(3)
    return {"skill": query, "chosen": chosen, "saved": saved}


def main():
    idx = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    todo = [SKILLS[idx]] if idx is not None else SKILLS
    results = []
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for s in todo:
            try:
                results.append(add_skill(page, s))
            except Exception as e:
                results.append({"skill": s, "ok": False, "reason": str(e)[:70]})
        ctx.close()
    for r in results:
        print(f"RESULT {r}")


if __name__ == "__main__":
    main()
