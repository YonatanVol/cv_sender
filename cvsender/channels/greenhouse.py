"""Greenhouse channel: discover (public feed) + frame-aware prepare + send with
DETERMINISTIC confirmation. Fixes v1's two crippling bugs: (1) it enters the
#grnhse_iframe embed frame before filling (v1 filled the top document and thus
filled nothing), and (2) success is a positive network/URL signal, never English
body-text sniffing.
"""
from __future__ import annotations

import asyncio
import html
import re
import time

import httpx

from ..config import SCREENSHOT_DIR, STEP_TIMEOUT_S, USER_AGENT
from ..engine import answerbank as ab
from .base import (READY, NEEDS_INPUT, FAILED, SENT, SENT_UNVERIFIED,
                   SEND_FAILED, ConfirmationEvidence, FieldFill, Job,
                   PrepareResult, Question, SendHandle, SendResult)

LIST_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_TAG = re.compile(r"<[^>]+>")

STD_FIELDS = [("#first_name", "first_name"), ("#last_name", "last_name"),
              ("#email", "email"), ("#phone", "phone")]


def _strip(text: str) -> str:
    return _TAG.sub(" ", html.unescape(text or "")).strip()


class GreenhouseChannel:
    channel = "greenhouse"

    def __init__(self, tokens: list[str]):
        self.tokens = tokens

    # ------------------------------ discover ------------------------------
    async def discover(self, spec: dict) -> list[Job]:
        jobs: list[Job] = []
        ct = spec.get("_cancel")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as c:
            for token in self.tokens:
                if ct is not None:
                    ct.check()          # cancel is responsive during discovery
                try:
                    r = await c.get(LIST_URL.format(token=token),
                                    params={"content": "true"})
                    if r.status_code != 200:
                        spec.setdefault("_health", {})[f"greenhouse:{token}"] = \
                            {"status": r.status_code, "jobs": 0}
                        continue
                    data = r.json()
                except (httpx.HTTPError, ValueError) as e:
                    spec.setdefault("_health", {})[f"greenhouse:{token}"] = \
                        {"status": f"error:{type(e).__name__}", "jobs": 0}
                    continue
                items = data.get("jobs", []) if isinstance(data, dict) else []
                for j in items:
                    ext = j.get("id")
                    if ext is None:
                        continue
                    loc = (j.get("location") or {}).get("name", "") or ""
                    url = j.get("absolute_url", "")
                    jobs.append(Job(
                        channel="greenhouse", company=token,
                        external_id=str(ext), title=j.get("title", ""),
                        location=loc, url=url, apply_url=url,
                        remote="remote" in loc.lower(),
                        description=_strip(j.get("content", "")),
                        raw={"id": ext},
                    ))
                spec.setdefault("_health", {})[f"greenhouse:{token}"] = \
                    {"status": 200, "jobs": len(items)}
        return jobs

    # ------------------------------ prepare -------------------------------
    async def prepare(self, ctx, job: Job, profile: dict, cv_path: str,
                      cancel) -> PrepareResult:
        page = await ctx.new_page()
        try:
            cancel.check()
            await cancel.guard(
                page.goto(job.apply_url, wait_until="domcontentloaded"),
                STEP_TIMEOUT_S)
            await cancel.sleep(1.3)
            root = await _form_root(page)

            # Prohibited-field / credential wall -> block, never fill.
            if await _has_prohibited(root):
                return PrepareResult(state=NEEDS_INPUT,
                                     reason="account/credential wall — complete manually")

            values = ab.profile_values(profile)
            filled: list[FieldFill] = []
            answers: dict = {}

            for sel, key in STD_FIELDS:
                el = await root.query_selector(sel)
                if el and values.get(key):
                    try:
                        await el.fill(values[key])
                        filled.append(FieldFill(key, values[key]))
                        answers[key] = values[key]
                    except Exception:
                        pass

            # Other recognized text inputs (linkedin/github/website/location).
            await _fill_labeled_text(root, values, filled, answers, page)

            cv_attached = await _attach_cv(root, cv_path)

            if await _has_captcha(root):
                shot = await _shot(page, job, root=root)
                return PrepareResult(state=NEEDS_INPUT, filled=filled,
                                     answers=answers, cv_attached=cv_attached,
                                     screenshot=shot, reason="CAPTCHA present")

            questions = await _required_unfilled(root)
            shot = await _shot(page, job, root=root)

            if not filled:
                return PrepareResult(state=NEEDS_INPUT, screenshot=shot,
                                     reason="no recognized form fields found")
            if not cv_attached:
                return PrepareResult(state=NEEDS_INPUT, filled=filled,
                                     answers=answers, screenshot=shot,
                                     reason="resume upload not found")
            if questions:
                return PrepareResult(state=NEEDS_INPUT, filled=filled,
                                     answers=answers, questions=questions,
                                     cv_attached=True, screenshot=shot,
                                     reason="unanswered required question(s)")
            return PrepareResult(state=READY, filled=filled, answers=answers,
                                 cv_attached=True, screenshot=shot,
                                 reason="ready to send")
        except Exception as e:
            return PrepareResult(state=FAILED, reason=f"{type(e).__name__}: {e}"[:160])
        finally:
            await page.close()

    # -------------------------------- send --------------------------------
    async def send(self, ctx, handle: SendHandle, cancel) -> SendResult:
        page = await ctx.new_page()
        try:
            cancel.check()
            await cancel.guard(
                page.goto(handle.apply_url, wait_until="domcontentloaded"),
                STEP_TIMEOUT_S)
            await cancel.sleep(1.3)
            root = await _form_root(page)

            # Re-fill deterministically from the durable handle (stateless send).
            for sel, key in STD_FIELDS:
                if handle.answers.get(key):
                    el = await root.query_selector(sel)
                    if el:
                        try:
                            await el.fill(handle.answers[key])
                        except Exception:
                            pass
            if not await _attach_cv(root, handle.cv_path):
                return SendResult(state=SEND_FAILED, reason="resume re-attach failed")

            submit = await _submit_button(root)
            if not submit:
                return SendResult(state=SEND_FAILED, reason="submit button not found")

            # Deterministic success: race a 2xx submit POST vs a /confirmation
            # navigation vs a confirmation node. No text sniffing.
            evidence = await _submit_and_verify(page, root, submit, cancel)
            shot = await _shot(page, None, suffix="after")
            if evidence:
                return SendResult(state=SENT, evidence=evidence, screenshot=shot)
            return SendResult(state=SENT_UNVERIFIED, screenshot=shot,
                              reason="submitted but no positive confirmation captured")
        except Exception as e:
            return SendResult(state=SEND_FAILED, reason=f"{type(e).__name__}: {e}"[:160])
        finally:
            await page.close()


# ------------------------------- helpers -----------------------------------

async def _form_root(page):
    """Return the frame that actually contains the application form."""
    try:
        await page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    if await page.query_selector("#first_name, input[autocomplete='given-name']"):
        return page.main_frame
    el = await page.query_selector(
        "iframe#grnhse_iframe, iframe[src*='greenhouse.io/embed'], "
        "iframe[src*='boards.greenhouse.io']")
    if el:
        fr = await el.content_frame()
        if fr:
            try:
                await fr.wait_for_selector("#first_name, input", timeout=8000)
            except Exception:
                pass
            return fr
    for f in page.frames:
        try:
            if await f.query_selector("#first_name"):
                return f
        except Exception:
            continue
    return page.main_frame


async def _field_key(root, el) -> str:
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


async def _fill_labeled_text(root, values, filled, answers, page):
    try:
        els = await root.query_selector_all(
            "input[type='text'], input[type='url'], input[type='email'], "
            "input[type='tel'], input:not([type])")
    except Exception:
        els = []
    for el in els:
        try:
            if not await el.is_visible():
                continue
            cur = await el.input_value()
            if cur:
                continue
            key = await _field_key(root, el)
            if ab.is_prohibited(key):
                continue
            vk = ab.match_text_field(key)
            if vk and vk not in ("first_name", "last_name", "email", "phone") \
                    and values.get(vk):
                await el.fill(values[vk])
                filled.append(FieldFill(vk, values[vk]))
                answers[vk] = values[vk]
        except Exception:
            continue


async def _attach_cv(root, cv_path: str) -> bool:
    if not cv_path:
        return False
    try:
        inputs = await root.query_selector_all("input[type='file']")
    except Exception:
        inputs = []
    for fi in inputs:
        key = await _field_key(root, fi)
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


async def _has_captcha(root) -> bool:
    for sel in ("iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
                ".g-recaptcha"):
        try:
            if await root.query_selector(sel):
                return True
        except Exception:
            continue
    return False


async def _has_prohibited(root) -> bool:
    try:
        if await root.query_selector("input[type='password']"):
            return True
    except Exception:
        pass
    try:
        for el in await root.query_selector_all("input, label"):
            key = await _field_key(root, el)
            if ab.is_prohibited(key):
                return True
    except Exception:
        pass
    return False


async def _required_unfilled(root) -> list[Question]:
    out: list[Question] = []
    try:
        els = await root.query_selector_all(
            "input[required], input[aria-required='true'], "
            "select[required], select[aria-required='true'], "
            "textarea[required], textarea[aria-required='true']")
    except Exception:
        els = []
    for el in els:
        try:
            if not await el.is_visible():
                continue
            t = (await el.get_attribute("type")) or "text"
            if t in ("hidden", "file"):
                continue
            val = ""
            try:
                val = await el.input_value()
            except Exception:
                pass
            if val:
                continue
            label = (await _field_key(root, el)).strip()[:100] or "required field"
            out.append(Question(label=label, kind="text",
                                reason="required, unrecognized"))
        except Exception:
            continue
    return out


async def _submit_button(root):
    for sel in ("#submit_app", "input[type='submit']", "button[type='submit']",
                "button:has-text('Submit Application')",
                "button:has-text('Submit application')"):
        try:
            b = await root.query_selector(sel)
            if b and await b.is_visible():
                return b
        except Exception:
            continue
    return None


async def _submit_and_verify(page, root, submit, cancel):
    """Click submit; return ConfirmationEvidence on a positive signal, else None."""
    resp_holder = {}

    def _match(resp):
        try:
            u = resp.url.lower()
            return ("greenhouse.io" in u and resp.request.method == "POST"
                    and ("job_app" in u or "application" in u))
        except Exception:
            return False

    async def _wait_response():
        try:
            resp = await page.wait_for_event(
                "response", predicate=_match, timeout=STEP_TIMEOUT_S * 1000)
            resp_holder["resp"] = resp
        except Exception:
            pass

    waiter = asyncio.ensure_future(_wait_response())
    try:
        await submit.click()
    except Exception:
        pass

    # Give the network / navigation a bounded window.
    deadline = time.time() + STEP_TIMEOUT_S
    while time.time() < deadline:
        cancel.check()
        if "resp" in resp_holder:
            r = resp_holder["resp"]
            if 200 <= r.status < 400:
                waiter.cancel()
                return ConfirmationEvidence("network", detail=r.url,
                                            http_status=r.status, at=time.time())
        try:
            if "/confirmation" in page.url.lower():
                waiter.cancel()
                return ConfirmationEvidence("url", detail=page.url, at=time.time())
            node = await root.query_selector(
                "#application_confirmation, .application--confirmation, "
                "[data-test='confirmation']")
            if node:
                waiter.cancel()
                return ConfirmationEvidence("dom", matched="confirmation-node",
                                            at=time.time())
        except Exception:
            pass
        await asyncio.sleep(0.5)
    waiter.cancel()
    return None


async def _shot(page, job, suffix: str = "prepare", root=None) -> str:
    try:
        # Scroll the filled form into view so the review card shows the form,
        # not the top-of-page job description.
        if root is not None:
            for sel in ("#first_name", "input[type='file']", "#submit_app"):
                el = await root.query_selector(sel)
                if el:
                    try:
                        await el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    break
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"gh_{int(time.time()*1000)}_{suffix}.png"
        path = SCREENSHOT_DIR / name
        await page.screenshot(path=str(path), full_page=False)
        return f"shots/{name}"
    except Exception:
        return ""
