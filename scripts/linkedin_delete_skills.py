"""Delete off-target skills by id (Hebrew UI). One skill per process run.

Delete button = 'מחיקת מיומנות'; a confirmation ('מחיקה'/אישור) may follow.

Usage:  python scripts/linkedin_delete_skills.py <skill_id>
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from app.apply import browser  # noqa: E402

SLUG = "yonatanvolsky"

# Off-target skills (id -> name) captured from the first skills scan.
TARGETS = {
    "750539478": "Telecommunications Engineering",
    "750408083": "Hardware",
    "750384160": "SQL Server Analysis Services (SSAS)",
    "750370442": "Communication Training",
    "750362104": "Oral Communication",
}


def edit_url(sid):
    return f"https://www.linkedin.com/in/{SLUG}/details/skills/edit/forms/{sid}/"


def delete_one(page, sid):
    page.goto(edit_url(sid), wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    del_btn = None
    for b in page.query_selector_all("button"):
        if (b.inner_text() or "").strip() == "מחיקת מיומנות" and b.is_visible():
            del_btn = b
            break
    if not del_btn:
        return {"id": sid, "ok": False, "reason": "delete button not found"}
    del_btn.click()
    time.sleep(2)
    confirmed = False
    for b in page.query_selector_all("div[role='dialog'] button, button"):
        t = (b.inner_text() or "").strip()
        if t in ("מחיקה", "אישור", "Delete", "כן"):
            try:
                b.click()
                confirmed = True
                break
            except Exception:
                pass
    time.sleep(3)
    return {"id": sid, "name": TARGETS.get(sid, "?"), "deleted": True,
            "confirmed": confirmed}


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    ids = [sid] if sid else list(TARGETS)
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for s in ids:
            try:
                print("RESULT", delete_one(page, s))
            except Exception as e:
                print("RESULT", {"id": s, "ok": False, "reason": str(e)[:70]})
        ctx.close()


if __name__ == "__main__":
    main()
