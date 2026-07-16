"""Upload a background banner for ANY person (isolated profile dir).

Usage: python scripts/li_set_banner.py <profile_slug> <banner_png>

Flow: profile -> click background-photo camera -> upload menu item (file
chooser) -> set file -> Apply/Save in the photo editor. Hebrew UI.
"""
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


def _click_primary(page, words):
    for b in page.query_selector_all("div[role='dialog'] button, button"):
        try:
            al = _norm(b.get_attribute("aria-label")).lower()
            tx = _norm(b.inner_text()).lower()
            if any(w in al or w in tx for w in words) and b.is_visible() and b.is_enabled():
                b.click()
                return True
        except Exception:
            continue
    return False


def main(profile_slug, banner_png):
    profile_dir = ROOT / "data" / "li_profiles" / profile_slug
    banner = str(Path(banner_png).resolve())
    with sync_playwright() as p:
        ctx = browser.launch_persistent(p, headless=False, user_data_dir=profile_dir)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)
        # open the background-photo menu
        opened = False
        for b in page.query_selector_all("button"):
            al = _norm(b.get_attribute("aria-label"))
            if "רקע" in al and b.is_visible():
                b.click(); opened = True; break
        if not opened:
            print("RESULT banner: camera button not found"); ctx.close(); return
        time.sleep(2)

        def find_text(words, sels=("[role='menuitem']", "button", "a", "div[role='button']")):
            for sel in sels:
                for el in page.query_selector_all(sel):
                    try:
                        if el.is_visible() and any(w in _norm(el.inner_text()) for w in words):
                            return el
                    except Exception:
                        continue
            return None

        # camera -> menu item 'הוספת תמונת כריכה' -> modal with 'העלאת תמונה בודדת'
        upload_btn = find_text(["העלאת תמונה", "העלאת", "upload"])
        if not upload_btn:
            menu = find_text(["כריכה"])
            if menu:
                menu.click()
                time.sleep(3)
            upload_btn = find_text(["העלאת תמונה", "העלאת", "upload"])
        if not upload_btn:
            print("RESULT banner: upload button not found"); ctx.close(); return
        try:
            with page.expect_file_chooser(timeout=15000) as fc:
                upload_btn.click()
            fc.value.set_files(banner)
        except Exception as e:
            print(f"RESULT banner: file chooser failed: {e}"[:120]); ctx.close(); return
        time.sleep(4)
        page.screenshot(path=str(ROOT / "data/screenshots/shani_banner_editor.png"))
        # apply/save in the editor (may take two clicks: Apply then Save)
        _click_primary(page, ["החל", "apply", "שמיר", "save"])
        time.sleep(2)
        _click_primary(page, ["שמיר", "save", "החל", "apply"])
        time.sleep(4)
        page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        page.screenshot(path=str(ROOT / "data/screenshots/shani_banner_done.png"))
        print("RESULT banner: uploaded (see shani_banner_done.png)")
        ctx.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: li_set_banner.py <profile_slug> <banner_png>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
