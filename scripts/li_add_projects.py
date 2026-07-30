"""Add Projects to a LinkedIn profile (Hebrew UI), one per process.

Usage: python scripts/li_add_projects.py <url_slug> <projects_json> [profile_slug]
  profile_slug: "default"/"-" (Yonatan's original dir) or a name under
                data/li_profiles/<name>.

Form: /in/<slug>/edit/forms/project/new/
  - first non-search text input  -> project name
  - textarea aria contains 'תיאור' -> description
The form has no URL field, so the project's link is appended to the description.
Dates are intentionally left empty (we don't invent them).
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
    return (s or "").translate({ord(c): None for c in _BIDI}).strip()


def _name_input(page):
    for e in page.query_selector_all("input"):
        try:
            if not e.is_visible():
                continue
            ph = _norm(e.get_attribute("placeholder"))
            al = _norm(e.get_attribute("aria-label"))
            if "חיפוש" in ph or "חיפוש" in al:
                continue
            if (e.get_attribute("type") or "text") not in ("text", ""):
                continue
            return e
        except Exception:
            continue
    return None


def _desc_field(page):
    for e in page.query_selector_all("textarea, div[contenteditable='true']"):
        try:
            if e.is_visible() and "תיאור" in _norm(e.get_attribute("aria-label")):
                return e
        except Exception:
            continue
    return None


def _save(page):
    for b in page.query_selector_all("button"):
        try:
            al = _norm(b.get_attribute("aria-label")).lower()
            tx = _norm(b.inner_text()).lower()
            if ("שמיר" in al or "שמיר" in tx or "save" in al or "save" in tx) \
                    and b.is_visible() and b.is_enabled():
                b.click()
                return True
        except Exception:
            continue
    return False


def add_one(page, slug, proj):
    page.goto(f"https://www.linkedin.com/in/{slug}/edit/forms/project/new/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(7)
    name = _name_input(page)
    if not name:
        return {"project": proj["name"], "ok": False, "reason": "name field not found"}
    name.click()
    name.fill(proj["name"])
    desc = _desc_field(page)
    if desc:
        body = proj["description"]
        if proj.get("url"):
            body = f"{body}\n\nLink: {proj['url']}"
        desc.click()
        try:
            desc.fill(body)
        except Exception:
            page.keyboard.type(body)
    time.sleep(0.5)
    saved = _save(page)
    time.sleep(4)
    page.goto(f"https://www.linkedin.com/in/{slug}/details/projects/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    ok = proj["name"][:18].lower() in (page.inner_text("body") or "").lower()
    return {"project": proj["name"][:32], "saved": saved, "verified": ok}


def main(slug, projects_json, profile_slug="default"):
    projs = json.loads(Path(projects_json).read_text(encoding="utf-8"))
    profile_dir = (None if profile_slug in ("default", "-")
                   else ROOT / "data" / "li_profiles" / profile_slug)
    for proj in projs:
        with sync_playwright() as p:
            ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                print(f"RESULT {add_one(page, slug, proj)}", flush=True)
            except Exception as e:
                print(f"RESULT {{'project': {proj['name'][:24]!r}, 'ok': False, "
                      f"'reason': {str(e)[:60]!r}}}", flush=True)
            finally:
                ctx.close()
        time.sleep(2)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: li_add_projects.py <url_slug> <projects_json> [profile_slug]")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "default")
