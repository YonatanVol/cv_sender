import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from app.apply import browser

_BIDI = "".join(chr(c) for c in (0x200e,0x200f,0x202a,0x202b,0x202c,0x202d,0x202e))
def norm(s): return (s or "").translate({ord(c):None for c in _BIDI}).strip().lower()
def issave(b):
    try: al=norm(b.get_attribute("aria-label")); tx=norm(b.inner_text())
    except: return False
    return "שמיר" in al or "שמיר" in tx or "save" in al or "save" in tx
def vis(e):
    try: return e.is_visible()
    except: return False

text = Path("data/assets/shani/headline.txt").read_text(encoding="utf-8").strip()
with sync_playwright() as p:
    ctx = browser.launch_persistent(p, headless=False, user_data_dir=ROOT/"data/li_profiles/shani")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.linkedin.com/in/shani-zahavi-039a76421/edit/intro/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    # fill headline
    eds=[e for e in page.query_selector_all("textarea, div[contenteditable='true']") if vis(e)]
    field=None
    for e in eds:
        try: v=e.input_value()
        except:
            try: v=e.inner_text() or ""
            except: v=""
        if any(k in v.lower() for k in ("student","holon","computer science")): field=e
    field=field or (eds[0] if len(eds)==1 else None)
    field.click(); time.sleep(0.3)
    page.keyboard.press("Meta+A"); page.keyboard.press("Delete"); time.sleep(0.2)
    page.keyboard.type(text)
    field.evaluate("el=>el.dispatchEvent(new Event('input',{bubbles:true}))")
    time.sleep(0.5)
    # enumerate ALL save buttons page-wide
    print("=== save buttons page-wide ===")
    cands=[]
    for b in page.query_selector_all("button"):
        if issave(b):
            try:
                box=b.bounding_box()
                print(f"  vis={b.is_visible()} en={b.is_enabled()} text={norm(b.inner_text())!r} aria={norm(b.get_attribute('aria-label'))!r} box={box}")
                if b.is_visible() and b.is_enabled(): cands.append(b)
            except Exception as ex: print("   err",str(ex)[:50])
    print("visible+enabled save candidates:", len(cands))
    # click the lowest-on-screen visible save (modal footer is near bottom)
    if cands:
        cands.sort(key=lambda b: (b.bounding_box() or {}).get("y", 0))
        target=cands[-1]
        print("clicking lowest save at y=", (target.bounding_box() or {}).get("y"))
        target.click()
    time.sleep(3)
    page.screenshot(path=str(ROOT/"data/screenshots/shani_hl_aftersave.png"))
    print("=== errors/alerts after save ===")
    for a in page.query_selector_all("[role='alert'], .artdeco-inline-feedback--error, .fb-field-error, [class*='error']"):
        t=(a.inner_text() or "").strip()
        if t: print("  ERR:", t[:160])
    d=page.query_selector("div[role='dialog']")
    print("dialog still open:", bool(d and vis(d)))
    if d:
        print("dialog text[:400]:", repr((d.inner_text() or '')[:400]))
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    print("new headline on profile:", text[:40] in (page.inner_text("body") or ""))
    ctx.close()
