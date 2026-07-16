import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from app.apply import browser
_BIDI="".join(chr(c) for c in (0x200e,0x200f,0x202a,0x202b,0x202c,0x202d,0x202e))
def norm(s): return (s or "").translate({ord(c):None for c in _BIDI}).strip().lower()

with sync_playwright() as p:
    ctx = browser.launch_persistent(p, headless=False, user_data_dir=ROOT/"data/li_profiles/shani")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.linkedin.com/in/shani-zahavi-039a76421/edit/intro/",
              wait_until="domcontentloaded", timeout=45000)
    time.sleep(6)
    # find industry input
    inp=None
    for i in page.query_selector_all("input"):
        al=norm(i.get_attribute("aria-label")); ph=norm(i.get_attribute("placeholder")); idv=norm(i.get_attribute("id"))
        if "תעשי" in al or "industr" in al or "תעשי" in ph or "industr" in idv:
            inp=i; print("industry input via attr:", repr(al), repr(idv)); break
    if not inp:
        for l in page.query_selector_all("label"):
            if "תעשי" in norm(l.inner_text()):
                fid=l.get_attribute("for")
                print("industry label for=",fid)
                if fid: inp=page.query_selector(f"#{fid}")
                break
    print("found industry input:", bool(inp))
    for q in ["Software Development","תוכנה","Information Technology"]:
        if not inp: break
        try:
            inp.click(); page.keyboard.press("Meta+A"); page.keyboard.press("Delete"); time.sleep(0.3)
            inp.type(q); time.sleep(1.8)
            opts=[o for o in page.query_selector_all("[role='option'], .basic-typeahead__selectable") if o.is_visible()]
            print(f"query {q!r} -> {len(opts)} options:", [norm(o.inner_text())[:40] for o in opts[:6]])
        except Exception as ex:
            print("  err", str(ex)[:60])
    ctx.close()
