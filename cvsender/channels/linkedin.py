"""LinkedIn Easy Apply channel (async). The most fragile channel by nature —
LinkedIn changes its DOM often and discourages automation — so it is deliberately
conservative: prepare() fills every step and STOPS at the final Submit (which it
never clicks), routing anything it can't answer to needs_input; send() performs
the one real submit only after the human confirm, and verifies the structural
"Application sent" view. Hard-stops on any security checkpoint. We never store
the password (one-time human login in the persistent profile).
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

from ..config import SCREENSHOT_DIR, STEP_TIMEOUT_S
from ..engine import answerbank as ab
from .base import (Question, READY, NEEDS_INPUT, FAILED, SENT, SEND_FAILED,
                   SEND_NEEDS_INPUT,
                   ConfirmationEvidence, FieldFill, Job, PrepareResult,
                   SendHandle, SendResult)

SEARCH = "https://www.linkedin.com/jobs/search/"
QUERIES = ["junior software developer", "student software developer",
           "software developer intern", "junior software engineer",
           "entry level software engineer", "junior full stack developer",
           "junior backend developer", "junior frontend developer",
           "junior python developer", "junior react developer",
           "junior web developer", "junior data analyst",
           "junior qa engineer", "associate software engineer",
           "graduate software engineer", "junior developer"]

NEXT = ["Continue to next step", "Next", "המשך", "המשך לשלב הבא"]
REVIEW = ["Review your application", "Review", "בדיקת המועמדות", "סקירה"]
SUBMIT = ["Submit application", "שליחת המועמדות", "שליחה", "Submit"]
DISMISS = ["Dismiss", "סגירה", "ביטול"]
DISCARD = ["Discard", "מחיקה", "מחק", "השלכה"]
CHECKPOINT = ("/checkpoint", "/authwall", "/uas/login")


# Scroll the virtualised results pane (the nearest scrollable ancestor of a job
# card) one screen at a time. Returns false once it can't scroll further.
_SCROLL_PANE_JS = """() => {
  const card = document.querySelector('[data-occludable-job-id], [data-job-id]');
  let el = card && card.parentElement;
  while (el && el !== document.body) {
    const st = getComputedStyle(el);
    if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 10) break;
    el = el.parentElement;
  }
  if (!el || el === document.body) { window.scrollBy(0, 2000); return false; }
  const before = el.scrollTop;
  el.scrollTop = before + el.clientHeight;
  return el.scrollTop > before;
}"""

_READ_CARDS_JS = """() => {
  const out = {};
  for (const c of document.querySelectorAll('[data-occludable-job-id], [data-job-id]')) {
    const id = c.getAttribute('data-occludable-job-id') || c.getAttribute('data-job-id');
    const lines = (c.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    if (!id || !lines.length) continue;
    if (!out[id] || lines.length > out[id].lines.length) out[id] = {id, lines};
  }
  return Object.values(out);
}"""


def cards_to_jobs(rows: list, location: str, query: str) -> list[Job]:
    """Turn raw card rows {id, lines:[title, (title again), company, location…]}
    into Jobs. Pure, so it is unit-tested without a browser."""
    jobs = []
    for r in rows or []:
        jid = str(r.get("id") or "").strip()
        lines = [l for l in (r.get("lines") or []) if l]
        if not jid.isdigit() or not lines:
            continue
        title = lines[0]
        rest = [l for l in lines[1:] if l != title and not l.startswith(title + " ")]
        company = rest[0][:60] if rest else "LinkedIn"
        loc = rest[1] if len(rest) > 1 else location
        jobs.append(Job(channel="linkedin", company=company, external_id=jid,
                        title=title, location=loc,
                        url=f"https://www.linkedin.com/jobs/view/{jid}/",
                        apply_url=f"https://www.linkedin.com/jobs/view/{jid}/",
                        description=""))
    return jobs


async def _card_company(anchor) -> str:
    """Pull the employer name off a search-result card so the UI shows the real
    company instead of 'linkedin' on every row."""
    try:
        card = await anchor.evaluate_handle(
            "el => el.closest('li, div.job-card-container, "
            "div.base-card, [data-job-id]')")
        if not card:
            return ""
        for sel in (".artdeco-entity-lockup__subtitle",
                    ".job-card-container__primary-description",
                    ".base-search-card__subtitle",
                    "[class*='subtitle']"):
            el = await card.as_element().query_selector(sel) if card.as_element() else None
            if el:
                txt = ((await el.inner_text()) or "").strip().split("\n")[0]
                if txt:
                    return txt[:60]
    except Exception:
        pass
    return ""



# One control, read with the label a human sees. Element-scoped on purpose:
# LinkedIn's apply dialog lives inside a shadow root, so a page-level
# document.querySelector finds nothing — Playwright's selectors pierce it, and
# this runs on each element it hands back.
_FIELD_JS = r"""el => {
  const root = el.getRootNode();
  const clean = t => (t || "").replace(/\s+/g, " ").replace(/^\*+|\*+$/g, "")
                              .replace(/\s*(Required|חובה)\s*$/i, "").trim().slice(0, 200);
  const optionOf = () => {            // this control's OWN text (a radio choice)
    if (el.id && root.querySelector) {
      const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText;
    }
    const wrap = el.closest("label");
    if (wrap && wrap.innerText.trim()) return wrap.innerText;
    return el.getAttribute("aria-label") || el.value || "";
  };
  const groupText = () => {           // the question a group of choices asks
    const grp = el.closest("fieldset, [role=radiogroup], [role=group]");
    if (!grp) return "";
    const lg = grp.querySelector("legend, h3, h4, [role=heading]");
    return lg && lg.innerText.trim() ? lg.innerText : "";
  };
  const labelText = () => {
    // A radio's own <label> is its choice ("Yes"), never the question. Ask the
    // fieldset first, or every yes/no question arrives called "Yes".
    if ((el.type || "").toLowerCase() === "radio") {
      const g = groupText();
      if (g) return g;
    }
    if (el.id && root.querySelector) {
      const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText;
    }
    const wrap = el.closest("label");
    if (wrap && wrap.innerText.trim()) return wrap.innerText;
    const g = groupText();
    if (g) return g;
    let n = el.previousElementSibling, hops = 0;
    while (n && hops++ < 3) {
      if (n.innerText && n.innerText.trim()) return n.innerText;
      n = n.previousElementSibling;
    }
    const par = el.parentElement;
    if (par && par.innerText && par.innerText.trim()) return par.innerText;
    return el.getAttribute("aria-label") || el.getAttribute("name") || "";
  };
  const own = () => clean(optionOf());
  return {
    tag: el.tagName, type: (el.type || "").toLowerCase(), id: el.id || "",
    name: el.name || "", required: !!(el.required || el.getAttribute("aria-required") === "true"),
    value: el.tagName === "SELECT" ? (el.value || "") : (el.value || ""),
    checked: !!el.checked, label: clean(labelText()), own: own(),
    options: el.tagName === "SELECT"
      ? [...el.options].map(o => clean(o.label || o.value)).filter(Boolean) : [],
  };
}"""

# 2026-09-22: the SDUI apply modal has neither role="dialog" nor
# .jobs-easy-apply-content, so the two legacy selectors matched ZERO controls and
# every screening question came back as the useless "required field flagged".
# The form elements carry stable ids (…easyApplyFormElement…) inside
# .fb-dash-form-element wrappers; match those too, and keep the old selectors for
# the modal LinkedIn still serves to some accounts.
_CONTROLS = ("div[role='dialog'] input, div[role='dialog'] select, "
             "div[role='dialog'] textarea, div.jobs-easy-apply-content input, "
             "div.jobs-easy-apply-content select, div.jobs-easy-apply-content textarea, "
             "[id*='easyApplyFormElement'], "
             ".fb-dash-form-element input, .fb-dash-form-element select, "
             ".fb-dash-form-element textarea, "
             ".jobs-easy-apply-form-section__grouping input, "
             ".jobs-easy-apply-form-section__grouping select, "
             ".jobs-easy-apply-form-section__grouping textarea")

# A select showing its own placeholder is unanswered, not answered.
_PLACEHOLDERS = ("select an option", "choose an option", "בחר אפשרות",
                 "בחירת אפשרות", "select...", "-", "--")


def is_placeholder(value: str) -> bool:
    """True when a control's value is the 'nothing chosen yet' placeholder."""
    return (value or "").strip().lower() in _PLACEHOLDERS


class LinkedInChannel:
    channel = "linkedin"

    async def logged_in(self, page) -> bool:
        try:
            await page.goto("https://www.linkedin.com/feed/",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
        except Exception:
            pass
        url = (page.url or "").lower()
        if any(c in url for c in CHECKPOINT):
            return False
        return "/login" not in url

    # ------------------------------ discover ------------------------------
    async def discover(self, page, geography: str = "israel_remote") -> list[Job]:
        """Collect Easy Apply junior roles from LinkedIn search.

        2026-09: result cards are virtualised. Only cards scrolled into view
        inside the results pane render a link, and wheel-scrolling the page does
        not scroll that pane, so the old anchor scan saw ~7 of ~25 jobs per page.
        We now scroll the pane itself and read every card's job id, title,
        company and location, across the first two result pages.
        """
        location = "Israel"
        seen: dict[str, Job] = {}
        for q in QUERIES:
            for start in (0, 25):
                params = {"keywords": q, "location": location, "f_AL": "true",
                          "f_E": "1,2", "sortBy": "DD"}
                if start:
                    params["start"] = str(start)
                try:
                    await page.goto(SEARCH + "?" + urlencode(params),
                                    wait_until="domcontentloaded", timeout=40000)
                    await page.wait_for_timeout(2500)
                except Exception:
                    break
                if any(c in (page.url or "").lower() for c in CHECKPOINT):
                    return list(seen.values())
                try:
                    for _ in range(10):
                        moved = await page.evaluate(_SCROLL_PANE_JS)
                        await page.wait_for_timeout(450)
                        if not moved:
                            break
                    rows = await page.evaluate(_READ_CARDS_JS)
                except Exception:
                    rows = []
                fresh = 0
                for job in cards_to_jobs(rows, location, q):
                    if job.external_id not in seen:
                        seen[job.external_id] = job
                        fresh += 1
                if len(rows) < 20 or not fresh:
                    break              # last page, or nothing new on page 2
        return list(seen.values())

    # ------------------------------ prepare -------------------------------
    # (helper _card_company is module-level, below)
    async def prepare(self, ctx, job: Job, profile: dict, cv_path: str,
                      cancel) -> PrepareResult:
        page = await ctx.new_page()
        try:
            cancel.check()
            await cancel.guard(page.goto(job.apply_url, wait_until="domcontentloaded"),
                               STEP_TIMEOUT_S)
            await page.wait_for_timeout(2000)
            if any(c in page.url.lower() for c in CHECKPOINT):
                return PrepareResult(state=NEEDS_INPUT,
                                     reason="LinkedIn checkpoint — verify manually")
            if not await self._open_modal(page):
                return PrepareResult(state=NEEDS_INPUT,
                                     reason="no Easy Apply (external apply)")
            res = await self._walk(page, profile, cv_path, cancel, submit=False)
            await self._discard(page)
            return res
        except Exception as e:
            return PrepareResult(state=FAILED, reason=f"{type(e).__name__}: {e}"[:150])
        finally:
            await page.close()

    # -------------------------------- send --------------------------------
    async def send(self, ctx, handle: SendHandle, cancel) -> SendResult:
        page = await ctx.new_page()
        try:
            cancel.check()
            await cancel.guard(page.goto(handle.apply_url, wait_until="domcontentloaded"),
                               STEP_TIMEOUT_S)
            await page.wait_for_timeout(2000)
            if any(c in page.url.lower() for c in CHECKPOINT):
                # Ambiguous: it may or may not have submitted. Hand it to the
                # human to verify — never guess either way.
                return SendResult(
                    state=SEND_NEEDS_INPUT,
                    reason="LinkedIn checkpoint — verify manually whether it sent")
            profile = {"phone": handle.answers.get("phone", ""),
                       "email": handle.answers.get("email", ""),
                       "first_name": handle.answers.get("first_name", ""),
                       "last_name": handle.answers.get("last_name", ""),
                       "linkedin": handle.answers.get("linkedin", ""),
                       "github": handle.answers.get("github", ""),
                       "location": handle.answers.get("location", "")}
            if not await self._open_modal(page):
                # One retry with a hard reload: the button is often just missing
                # from a cached/draft render.
                try:
                    await cancel.guard(page.reload(wait_until="domcontentloaded"),
                                       STEP_TIMEOUT_S)
                    await page.wait_for_timeout(2500)
                except Exception:
                    pass
                if not await self._open_modal(page):
                    # Degrade to the assist queue with a working link rather than
                    # a dead 'failed' — a human can still finish this in seconds.
                    return SendResult(
                        state=SEND_NEEDS_INPUT,
                        reason="Easy Apply button not available — open and apply manually")
            res = await self._walk(page, profile, handle.cv_path, cancel, submit=True)
            if res.state == "submitted":
                ev = ConfirmationEvidence("dom", matched="application-sent",
                                          at=time.time())
                return SendResult(state=SENT, evidence=ev)
            # Couldn't confirm a submit: keep it retryable/finishable, never
            # claim it was sent.
            return SendResult(state=SEND_NEEDS_INPUT,
                              reason=res.reason or "did not reach submit")
        except Exception as e:
            return SendResult(state=SEND_FAILED, reason=f"{type(e).__name__}: {e}"[:150])
        finally:
            await page.close()

    # ------------------------------ helpers -------------------------------
    async def _open_modal(self, page) -> bool:
        # 2026-09: LinkedIn replaced the Easy Apply <button> with an <a> that opens
        # the server-driven apply flow (…/apply/?openSDUIApplyFlow=true), labelled
        # in the UI language. External-apply links never carry openSDUIApplyFlow.
        for sel in ("a[href*='openSDUIApplyFlow']",
                    "a[aria-label*='Easy Apply']",
                    "a[aria-label*='הגשת מועמדות בקלות']",
                    "button.jobs-apply-button",
                    "button[aria-label*='Easy Apply']",
                    "button[aria-label*='הגשת מועמדות בקלות']",
                    "button:has-text('Easy Apply')"):
            try:
                b = await page.query_selector(sel)
                if b and await b.is_visible():
                    if not await self._click(b):
                        continue
                    await page.wait_for_timeout(1800)
                    return True
            except Exception:
                continue
        return False

    async def _walk(self, page, profile, cv_path, cancel, submit: bool):
        """Step through the modal. Returns PrepareResult (prepare) or a
        lightweight result whose .state == 'submitted' on a real send."""
        filled: list[FieldFill] = []
        answers = {"phone": profile.get("phone", ""),
                   "email": profile.get("email", ""),
                   "location": profile.get("location", "")}
        for _ in range(8):
            cancel.check()
            await self._upload(page, cv_path)
            missing = await self._fill_step(page, profile, filled)
            if missing:
                shot = await self._capture(page)
                return PrepareResult(
                    state=NEEDS_INPUT, filled=filled, answers=answers,
                    questions=missing, screenshot=shot,
                    reason="Answer " + ("1 question" if len(missing) == 1
                                        else f"{len(missing)} questions")
                           + ": " + "; ".join(q.label[:40] for q in missing[:2]))
            sub = await self._find(page, SUBMIT)
            if sub:
                if not submit:
                    shot = await self._capture(page)
                    return PrepareResult(state=READY, filled=filled, answers=answers,
                                         cv_attached=True, screenshot=shot,
                                         reason="ready (reached submit)")
                await self._click(sub)
                # The confirmation view can take several seconds to render; two
                # of seven real sends on 2026-09-14 were missed at a fixed 2.5s.
                ok = False
                for _ in range(12):
                    await page.wait_for_timeout(1000)
                    if await self._sent(page):
                        ok = True
                        break
                return PrepareResult(state=("submitted" if ok else "failed"),
                                     reason="" if ok else "no 'Application sent' view")
            nxt = await self._find(page, REVIEW + NEXT)
            if not nxt:
                return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                     reason="stuck (no next/submit)")
            if not await self._click(nxt):
                break
            await page.wait_for_timeout(1500)
            if await self._error_flagged(page):
                asked: list[Question] = []
                await self._fill_step(page, profile, filled, asked)
                shot = await self._capture(page)
                return PrepareResult(
                    state=NEEDS_INPUT, filled=filled, answers=answers,
                    questions=asked, screenshot=shot,
                    reason=("Answer " + ("1 question" if len(asked) == 1
                                         else f"{len(asked)} questions") + ": "
                            + "; ".join(q.label[:40] for q in asked[:2]))
                           if asked else "required field flagged")
        return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                             reason="too many steps")

    async def _read_fields(self, page) -> list[dict]:
        """Every visible control in the apply dialog, with its visible label."""
        out: list[dict] = []
        radios: dict[str, dict] = {}
        try:
            els = await page.query_selector_all(_CONTROLS)
        except Exception:
            return out
        for el in els:
            try:
                if not await el.is_visible():
                    continue
                f = await el.evaluate(_FIELD_JS)
            except Exception:
                continue
            if f["type"] in ("hidden", "file", "submit", "button"):
                continue
            if f["tag"] not in ("INPUT", "SELECT", "TEXTAREA"):
                continue     # the id selector also matches the wrapper <div>
            f["el"] = el
            if f["type"] == "radio":
                key = f["name"] or f["label"]
                g = radios.setdefault(key, {"kind": "radio", "label": f["label"],
                                            "name": f["name"], "options": [],
                                            "required": False, "value": "", "els": []})
                g["label"] = g["label"] or f["label"]
                g["required"] = g["required"] or f["required"]
                if f["own"]:
                    g["options"].append(f["own"])
                    g["els"].append((f["own"], el))
                if f["checked"]:
                    g["value"] = f["own"]
                continue
            kind = ("checkbox" if f["type"] == "checkbox"
                    else "select" if f["tag"] == "SELECT" else "text")
            value = f["value"]
            if kind == "select" and is_placeholder(value):
                value = ""                 # "Select an option" is not an answer
            out.append({**f, "kind": kind,
                        "value": ("Yes" if f["checked"] else "") if kind == "checkbox" else value})
        return out + list(radios.values())

    async def _fill_step(self, page, profile, filled, asked=None):
        """Fill what we know; return the questions we will not invent answers to.

        Every control is read with its visible label, so an unanswered question
        reaches the human as a real question ("What is your GPA?") instead of
        the old useless 'required field flagged'. Answers learned once are
        reused on every later application.
        """
        vals = ab.profile_values(profile)
        missing: list[Question] = []
        for f in await self._read_fields(page):
            label = (f.get("label") or "").strip()
            kind = f.get("kind")
            if not label or ab.is_prohibited(label):
                continue
            if f.get("value"):
                continue                       # already answered / prefilled
            ans = None
            if kind == "text":
                vk = ab.match_text_field(label.lower())
                if vk and vals.get(vk):
                    ans = vals[vk]
            if ans is None:
                ans = ab.known_answer(label, profile)
            if ans is not None and await self._apply_answer(page, f, str(ans)):
                filled.append(FieldFill(label[:60], str(ans)))
                continue
            if f.get("required"):
                missing.append(Question(label=label[:200], kind=kind or "text",
                                        options=[o for o in (f.get("options") or []) if o][:12],
                                        required=True,
                                        reason="needs your answer once"))
        if asked is not None:
            asked.extend(missing)
        return missing

    async def _apply_answer(self, page, field: dict, answer: str) -> bool:
        """Put one answer into one control. False if it could not be applied."""
        kind, el = field.get("kind"), field.get("el")
        try:
            if kind == "text" and el:
                await el.fill(answer)
                return True
            if kind == "select" and el:
                for how in ("label", "value"):
                    try:
                        await el.select_option(**{how: answer})
                        return True
                    except Exception:
                        continue
                match = next((o for o in (field.get("options") or [])
                              if answer.lower() in o.lower() or o.lower() in answer.lower()), None)
                if match:
                    await el.select_option(label=match)
                    return True
                return False
            if kind == "checkbox" and el:
                if answer.strip().lower() in ("yes", "true", "1", "on", "כן"):
                    await el.check()
                    return True
                return False
            if kind == "radio":
                want = answer.strip().lower()
                for text, rel in field.get("els") or []:
                    t = (text or "").strip().lower()
                    if t == want or (want and (want in t or t.startswith(want[:20]))):
                        return await self._click(rel)
                return False
        except Exception:
            return False
        return False

    async def _upload(self, page, cv_path):
        if not cv_path:
            return
        try:
            fi = await page.query_selector("input[type='file']")
            if fi:
                await fi.set_input_files(cv_path)
        except Exception:
            pass

    async def _click(self, el, timeout: float = 8000) -> bool:
        """Click resiliently.

        Raw ElementHandle.click() waits the full default timeout (30s) whenever
        the element is covered by an overlay or re-rendered mid-step, which is
        what produced the 'ElementHandle.click: Timeout 30000ms' failures. Use a
        short timeout, scroll it into view, and fall back to a DOM-level click.
        """
        try:
            await el.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            await el.click(timeout=timeout)
            return True
        except Exception:
            pass
        try:                       # overlay / re-render fallback
            await el.evaluate("e => e.click()")
            return True
        except Exception:
            return False

    async def _find(self, page, texts):
        for t in texts:
            for sel in (f"button[aria-label*='{t}']", f"button:has-text('{t}')"):
                try:
                    b = await page.query_selector(sel)
                    if b and await b.is_visible() and await b.is_enabled():
                        return b
                except Exception:
                    continue
        return None

    async def _error_flagged(self, page) -> bool:
        try:
            return bool(await page.query_selector(".artdeco-inline-feedback--error"))
        except Exception:
            return False

    async def _sent(self, page) -> bool:
        """Positive evidence only. The confirmation text must be visible AND the
        submit button must be gone, so an unrelated "נשלחה" elsewhere on the page
        (a messaging preview, a notification) can never count as a send."""
        if await self._find(page, SUBMIT):
            return False
        for t in ("Application sent", "Your application was sent",
                  "המועמדות שלך נשלחה", "המועמדות נשלחה"):
            try:
                el = await page.query_selector(
                    f"div[role='dialog'] :text('{t}'), h2:has-text('{t}'), h3:has-text('{t}')")
                if el and await el.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _capture(self, page) -> str:
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            name = f"linkedin_{int(time.time()*1000)}.png"
            await page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=False)
            return f"shots/{name}"
        except Exception:
            return ""

    async def _discard(self, page):
        try:
            x = await self._find(page, DISMISS)
            if x:
                await self._click(x)
                await page.wait_for_timeout(700)
            d = await self._find(page, DISCARD)
            if d:
                await self._click(d)
                await page.wait_for_timeout(400)
        except Exception:
            pass
