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
                   SEND_FAILED, ConfirmationEvidence, FieldFill, Job,
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


async def has_captcha(root) -> bool:
    for sel in ("iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", ".g-recaptcha"):
        try:
            if await root.query_selector(sel):
                return True
        except Exception:
            continue
    return False


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


async def required_unfilled(root) -> list[Question]:
    out: list[Question] = []
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
            t = (await el.get_attribute("type")) or "text"
            if t in ("hidden", "file"):
                continue
            if (await el.input_value()):
                continue
            label = (await field_key(root, el)).strip()[:100] or "required field"
            out.append(Question(label=label, reason="required, unrecognized"))
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
        return SendResult(state=SENT_UNVERIFIED, screenshot=s,
                          reason="submitted but no positive confirmation captured")
    except Exception as e:
        return SendResult(state=SEND_FAILED, reason=f"{type(e).__name__}: {e}"[:160])
    finally:
        await page.close()


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
