"""Shared, label-driven ATS form engine for the standardized hosted forms
(Lever, Ashby, Comeet). Greenhouse keeps its own module because it needs the
#grnhse_iframe frame resolution; everything else fills by label and verifies via
a positive network/URL/DOM signal (never text-sniffing).
"""
from __future__ import annotations

import asyncio
import time

from ..config import SCREENSHOT_DIR, STEP_TIMEOUT_S
from ..engine import answerbank as ab
from .base import (READY, NEEDS_INPUT, FAILED, SENT, SENT_UNVERIFIED,
                   SEND_FAILED, SEND_NEEDS_INPUT, ConfirmationEvidence, FieldFill, Job,
                   PrepareResult, Question, SendHandle, SendResult)


async def field_key(root, el) -> str:
    parts = []
    for attr in ("name", "id", "placeholder", "aria-label"):
        try:
            v = await el.get_attribute(attr)
        except Exception:
            v = None
        if v:
            parts.append(v)
    try:
        eid = await el.get_attribute("id")
        if eid:
            lab = await root.query_selector(f"label[for='{eid}']")
            if lab:
                parts.append((await lab.inner_text()) or "")
    except Exception:
        pass
    return " ".join(parts).lower()


async def fill_all_text(root, values, filled, answers):
    try:
        els = await root.query_selector_all(
            "input[type='text'], input[type='url'], input[type='email'], "
            "input[type='tel'], input:not([type]), textarea")
    except Exception:
        els = []
    for el in els:
        try:
            if not await el.is_visible():
                continue
            if (await el.input_value()):
                continue
            key = await field_key(root, el)
            if ab.is_prohibited(key):
                continue
            vk = ab.match_text_field(key)
            if vk and values.get(vk):
                await el.fill(values[vk])
                filled.append(FieldFill(vk, values[vk]))
                answers[vk] = values[vk]
        except Exception:
            continue


async def attach_cv(root, cv_path: str) -> bool:
    if not cv_path:
        return False
    try:
        inputs = await root.query_selector_all("input[type='file']")
    except Exception:
        inputs = []
    for fi in inputs:
        key = await field_key(root, fi)
        if any(w in key for w in ("resume", "cv", "attach", "file")):
            try:
                await fi.set_input_files(cv_path)
                return True
            except Exception:
                continue
    if inputs:
        try:
            await inputs[0].set_input_files(cv_path)
            return True
        except Exception:
            return False
    return False


# A reCAPTCHA iframe is NOT a challenge. Every Greenhouse page carries the
# invisible reCAPTCHA v3 "badge" (a 256x60 anchor iframe inside .grecaptcha-badge)
# that no human ever touches. Treating it as a blocker parked 137 fully-filled
# applications — CV attached, no open questions — behind a badge.
#
# Blocking means a human must interact: a checkbox widget, an hCaptcha or
# Turnstile widget, or an open challenge frame.
_CAPTCHA_JS = r"""() => {
  const box = el => { const r = el.getBoundingClientRect();
                      return {w: r.width, h: r.height, vis: r.width > 20 && r.height > 20}; };
  // 1. an open challenge popup (only exists once a human is being asked)
  for (const f of document.querySelectorAll("iframe[src*='/bframe'], iframe[src*='hcaptcha.com/captcha']")) {
    if (box(f).vis) return "challenge";
  }
  // 2. an interactive widget that is not the invisible badge
  for (const w of document.querySelectorAll(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]")) {
    if (w.closest(".grecaptcha-badge")) continue;
    if ((w.getAttribute("data-size") || "").toLowerCase() === "invisible") continue;
    if (box(w).vis) return "widget";
  }
  // 3. a visible captcha iframe outside the badge (checkbox widgets render one)
  for (const f of document.querySelectorAll("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile']")) {
    if (f.closest(".grecaptcha-badge")) continue;
    const b = box(f);
    if (b.vis && b.h > 70) return "iframe";          // badge is 60px tall
  }
  return "";
}"""


async def captcha_kind(root) -> str:
    """'' when nothing blocks a human, else which kind of challenge was found."""
    try:
        return await root.evaluate(_CAPTCHA_JS) or ""
    except Exception:
        return ""


async def has_captcha(root) -> bool:
    """True only for a challenge a human must actually solve."""
    return bool(await captcha_kind(root))


async def has_prohibited(root) -> bool:
    try:
        if await root.query_selector("input[type='password']"):
            return True
        for el in await root.query_selector_all("input, label"):
            if ab.is_prohibited(await field_key(root, el)):
                return True
    except Exception:
        pass
    return False


# The label a person sees, read from the element outwards. The old version
# concatenated name+id+placeholder+aria-label, which produced
# "question_67972490 are you legally authorized…" and "country country*" —
# unreadable, and useless on the answers page.
_LABEL_JS = r"""el => {
  const root = el.getRootNode();
  const clean = t => (t || "").replace(/\s+/g, " ").replace(/\*+$/, "").trim().slice(0, 160);
  if (el.id && root.querySelector) {
    const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (l && l.innerText.trim()) return clean(l.innerText);
  }
  const wrap = el.closest("label");
  if (wrap && wrap.innerText.trim()) return clean(wrap.innerText);
  const grp = el.closest("fieldset, [role=group], [role=radiogroup], .field, div");
  if (grp) {
    const lg = grp.querySelector("legend, label, h3, h4, [role=heading]");
    if (lg && lg.innerText.trim()) return clean(lg.innerText);
  }
  return clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") || "");
}"""

_OPTIONS_JS = """el => el.tagName === 'SELECT'
  ? [...el.options].map(o => (o.label || o.value || '').trim()).filter(Boolean).slice(0, 25)
  : []"""


_COUNTRY_WORDS = ("country", "מדינה")


async def fill_known_selects(root, profile: dict, filled: list) -> int:
    """Answer the dropdowns a person would not think of as questions.

    Greenhouse validates its own Country select, so an application that looked
    ready was rejected on submit with "Select a country".
    """
    from ..engine import answerbank as ab
    n = 0
    try:
        selects = await root.query_selector_all("select")
    except Exception:
        return 0
    country = (profile.get("country") or
               ("Israel" if "israel" in (profile.get("location") or "").lower() else ""))
    for el in selects:
        try:
            if not await el.is_visible() or (await el.input_value()):
                continue
            label = (await el.evaluate(_LABEL_JS) or "").strip()
            if not label or ab.is_prohibited(label):
                continue
            answer = None
            if any(w in label.lower() for w in _COUNTRY_WORDS) and country:
                answer = country
            else:
                answer = ab.known_answer(label, profile)
            if not answer:
                continue
            for how in ("label", "value"):
                try:
                    await el.select_option(**{how: answer})
                    filled.append(FieldFill(label[:60], answer))
                    n += 1
                    break
                except Exception:
                    continue
        except Exception:
            continue
    return n


async def required_unfilled(root) -> list[Question]:
    """Questions a human must answer, with the wording they would recognise."""
    out: list[Question] = []
    seen: set[str] = set()
    try:
        els = await root.query_selector_all(
            "input[required], input[aria-required='true'], select[required], "
            "select[aria-required='true'], textarea[required], "
            "textarea[aria-required='true']")
    except Exception:
        els = []
    for el in els:
        try:
            if not await el.is_visible():
                continue
            t = ((await el.get_attribute("type")) or "text").lower()
            if t in ("hidden", "file", "submit", "button"):
                continue
            if t in ("checkbox", "radio"):
                if await el.is_checked():
                    continue
            elif (await el.input_value()):
                continue
            label = (await el.evaluate(_LABEL_JS) or "").strip()
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            options = await el.evaluate(_OPTIONS_JS) or []
            kind = ("select" if options else
                    "checkbox" if t == "checkbox" else
                    "radio" if t == "radio" else "text")
            out.append(Question(label=label[:160], kind=kind, options=options[:12],
                                required=True, reason="needs your answer once"))
        except Exception:
            continue
    return out


async def shot(page, suffix, root=None) -> str:
    try:
        if root is not None:
            for sel in ("input[type='file']", "button[type='submit']",
                        "input[name='name']", "input[name='email']"):
                el = await root.query_selector(sel)
                if el:
                    try:
                        await el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    break
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{suffix}_{int(time.time()*1000)}.png"
        await page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=False)
        return f"shots/{name}"
    except Exception:
        return ""


async def prepare_generic(ctx, job: Job, profile: dict, cv_path: str, cancel,
                          resolve_root, channel: str) -> PrepareResult:
    page = await ctx.new_page()
    try:
        cancel.check()
        await cancel.guard(page.goto(job.apply_url, wait_until="domcontentloaded"),
                           STEP_TIMEOUT_S)
        await cancel.sleep(1.5)
        root = await resolve_root(page)
        if root is None:
            return PrepareResult(state=NEEDS_INPUT,
                                 reason="application form not found (external apply?)")
        if await has_prohibited(root):
            return PrepareResult(state=NEEDS_INPUT,
                                 reason="account/credential wall — complete manually")

        values = ab.profile_values(profile)
        filled: list[FieldFill] = []
        answers: dict = {}
        await fill_all_text(root, values, filled, answers)
        await fill_known_selects(root, profile, filled)
        cv_attached = await attach_cv(root, cv_path)

        if await has_captcha(root):
            return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                 cv_attached=cv_attached,
                                 screenshot=await shot(page, channel, root),
                                 reason="CAPTCHA present")
        questions = await required_unfilled(root)
        s = await shot(page, channel, root)
        if not filled:
            return PrepareResult(state=NEEDS_INPUT, screenshot=s,
                                 reason="no recognized form fields found")
        if not cv_attached:
            return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                 screenshot=s, reason="resume upload not found")
        if questions:
            return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                 questions=questions, cv_attached=True,
                                 screenshot=s, reason="unanswered required question(s)")
        return PrepareResult(state=READY, filled=filled, answers=answers,
                             cv_attached=True, screenshot=s, reason="ready to send")
    except Exception as e:
        return PrepareResult(state=FAILED, reason=f"{type(e).__name__}: {e}"[:160])
    finally:
        await page.close()


async def send_generic(ctx, handle: SendHandle, cancel, resolve_root,
                       submit_selectors, net_host, confirm_url, confirm_sel):
    page = await ctx.new_page()
    try:
        cancel.check()
        await cancel.guard(page.goto(handle.apply_url, wait_until="domcontentloaded"),
                           STEP_TIMEOUT_S)
        await cancel.sleep(1.5)
        root = await resolve_root(page)
        if root is None:
            return SendResult(state=SEND_FAILED, reason="form not found at send time")
        values = dict(handle.answers)
        filled: list = []
        await fill_all_text(root, values, filled, {})
        await fill_known_selects(root, values, filled)
        if not await attach_cv(root, handle.cv_path):
            return SendResult(state=SEND_FAILED, reason="resume re-attach failed")

        submit = None
        for sel in submit_selectors:
            submit = await root.query_selector(sel)
            if submit and await submit.is_visible():
                break
            submit = None
        if not submit:
            return SendResult(state=SEND_FAILED, reason="submit button not found")

        ev = await _submit_and_verify(page, root, submit, cancel, net_host,
                                      confirm_url, confirm_sel)
        s = await shot(page, "after", root)
        if ev:
            return SendResult(state=SENT, evidence=ev, screenshot=s)
        # The form may have refused the submit outright — a required field it
        # validates itself (Country, a consent box). That is NOT "maybe sent":
        # nothing left the browser, and calling it unverified would park a
        # perfectly fixable application in limbo.
        rejected = await validation_errors(root)
        if rejected:
            return SendResult(state=SEND_NEEDS_INPUT, screenshot=s,
                              reason="the form refused it: " + "; ".join(rejected[:3]))
        return SendResult(state=SENT_UNVERIFIED, screenshot=s,
                          reason="submitted but no positive confirmation captured")
    except Exception as e:
        return SendResult(state=SEND_FAILED, reason=f"{type(e).__name__}: {e}"[:160])
    finally:
        await page.close()


_ERRORS_JS = r"""() => {
  const out = [];
  const label = el => {
    const f = el.closest("label, .field, fieldset, div");
    const l = f && f.querySelector("label, legend");
    return ((l && l.innerText) || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().slice(0, 60);
  };
  for (const el of document.querySelectorAll("[aria-invalid='true'], .error, [class*='error']")) {
    const t = (el.innerText || "").replace(/\s+/g, " ").trim();
    if (t && t.length < 120 && !/^\s*$/.test(t)) out.push(t);
  }
  for (const el of document.querySelectorAll("input, select, textarea")) {
    if (el.willValidate && !el.checkValidity()) {
      const name = label(el) || el.name || el.id;
      if (name) out.push(`${name}: ${el.validationMessage || "required"}`);
    }
  }
  return [...new Set(out)].slice(0, 6);
}"""


async def validation_errors(root) -> list[str]:
    """What the form itself is complaining about, in its own words."""
    try:
        return await root.evaluate(_ERRORS_JS) or []
    except Exception:
        return []


async def _submit_and_verify(page, root, submit, cancel, net_host, confirm_url,
                             confirm_sel):
    holder = {}

    def _match(resp):
        try:
            return (net_host in resp.url.lower()
                    and resp.request.method in ("POST", "PUT"))
        except Exception:
            return False

    async def _wait():
        try:
            holder["resp"] = await page.wait_for_event(
                "response", predicate=_match, timeout=STEP_TIMEOUT_S * 1000)
        except Exception:
            pass

    waiter = asyncio.ensure_future(_wait())
    try:
        await submit.click()
    except Exception:
        pass
    deadline = time.time() + STEP_TIMEOUT_S
    while time.time() < deadline:
        cancel.check()
        if "resp" in holder and 200 <= holder["resp"].status < 400:
            waiter.cancel()
            return ConfirmationEvidence("network", detail=holder["resp"].url,
                                        http_status=holder["resp"].status, at=time.time())
        try:
            if confirm_url and confirm_url in page.url.lower():
                waiter.cancel()
                return ConfirmationEvidence("url", detail=page.url, at=time.time())
            for sel in confirm_sel:
                if await root.query_selector(sel):
                    waiter.cancel()
                    return ConfirmationEvidence("dom", matched=sel, at=time.time())
        except Exception:
            pass
        await asyncio.sleep(0.5)
    waiter.cancel()
    return None
