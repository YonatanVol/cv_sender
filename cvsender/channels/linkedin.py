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
from .base import (READY, NEEDS_INPUT, FAILED, SENT, SEND_FAILED,
                   ConfirmationEvidence, FieldFill, Job, PrepareResult,
                   SendHandle, SendResult)

SEARCH = "https://www.linkedin.com/jobs/search/"
QUERIES = ["junior software developer", "student software developer",
           "software developer intern", "junior software engineer",
           "entry level software engineer"]

NEXT = ["Continue to next step", "Next", "המשך", "המשך לשלב הבא"]
REVIEW = ["Review your application", "Review", "בדיקת המועמדות", "סקירה"]
SUBMIT = ["Submit application", "שליחת המועמדות", "שליחה", "Submit"]
DISMISS = ["Dismiss", "סגירה", "ביטול"]
DISCARD = ["Discard", "מחיקה", "מחק", "השלכה"]
CHECKPOINT = ("/checkpoint", "/authwall", "/uas/login")


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
        location = "Israel"
        seen: dict[str, Job] = {}
        for q in QUERIES:
            params = {"keywords": q, "location": location, "f_AL": "true",
                      "f_E": "1,2", "sortBy": "DD"}
            try:
                await page.goto(SEARCH + "?" + urlencode(params),
                                wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(2500)
            except Exception:
                continue
            for _ in range(4):
                try:
                    await page.mouse.wheel(0, 2500)
                    await page.wait_for_timeout(800)
                except Exception:
                    break
            try:
                anchors = await page.query_selector_all("a[href*='/jobs/view/']")
            except Exception:
                anchors = []
            for a in anchors:
                try:
                    href = await a.get_attribute("href") or ""
                    if "/jobs/view/" not in href:
                        continue
                    jid = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                    if not jid or jid in seen:
                        continue
                    title = ((await a.inner_text()) or "").strip().split("\n")[0]
                    seen[jid] = Job(
                        channel="linkedin", company="linkedin",
                        external_id=jid, title=title or q, location=location,
                        url=f"https://www.linkedin.com/jobs/view/{jid}/",
                        apply_url=f"https://www.linkedin.com/jobs/view/{jid}/",
                        description="")
                except Exception:
                    continue
        return list(seen.values())

    # ------------------------------ prepare -------------------------------
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
                return SendResult(state=SEND_FAILED,
                                  reason="LinkedIn checkpoint — may not have submitted")
            profile = {"phone": handle.answers.get("phone", ""),
                       "email": handle.answers.get("email", ""),
                       "first_name": handle.answers.get("first_name", ""),
                       "last_name": handle.answers.get("last_name", ""),
                       "linkedin": handle.answers.get("linkedin", ""),
                       "github": handle.answers.get("github", ""),
                       "location": handle.answers.get("location", "")}
            if not await self._open_modal(page):
                return SendResult(state=SEND_FAILED, reason="Easy Apply not available")
            res = await self._walk(page, profile, handle.cv_path, cancel, submit=True)
            if res.state == "submitted":
                ev = ConfirmationEvidence("dom", matched="application-sent",
                                          at=time.time())
                return SendResult(state=SENT, evidence=ev)
            return SendResult(state=SEND_FAILED, reason=res.reason or "did not submit")
        except Exception as e:
            return SendResult(state=SEND_FAILED, reason=f"{type(e).__name__}: {e}"[:150])
        finally:
            await page.close()

    # ------------------------------ helpers -------------------------------
    async def _open_modal(self, page) -> bool:
        for sel in ("button.jobs-apply-button",
                    "button[aria-label*='Easy Apply']",
                    "button:has-text('Easy Apply')"):
            try:
                b = await page.query_selector(sel)
                if b and await b.is_visible():
                    await b.click()
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
                return PrepareResult(state=NEEDS_INPUT, filled=filled,
                                     answers=answers,
                                     reason="needs answers: " + "; ".join(missing[:2]))
            sub = await self._find(page, SUBMIT)
            if sub:
                if not submit:
                    shot = await self._capture(page)
                    return PrepareResult(state=READY, filled=filled, answers=answers,
                                         cv_attached=True, screenshot=shot,
                                         reason="ready (reached submit)")
                await sub.click()
                await page.wait_for_timeout(2500)
                ok = await self._sent(page)
                return PrepareResult(state=("submitted" if ok else "failed"),
                                     reason="" if ok else "no 'Application sent' view")
            nxt = await self._find(page, REVIEW + NEXT)
            if not nxt:
                return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                     reason="stuck (no next/submit)")
            await nxt.click()
            await page.wait_for_timeout(1500)
            if await self._error_flagged(page):
                return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                                     reason="required field flagged")
        return PrepareResult(state=NEEDS_INPUT, filled=filled, answers=answers,
                             reason="too many steps")

    async def _fill_step(self, page, profile, filled) -> list[str]:
        missing: list[str] = []
        scope = "div.jobs-easy-apply-content, div[role='dialog']"
        try:
            els = await page.query_selector_all(
                f"{scope} input[type='text'], {scope} input[type='tel'], "
                f"{scope} input[type='email'], {scope} textarea")
        except Exception:
            els = []
        vals = ab.profile_values(profile)
        for el in els:
            try:
                if not await el.is_visible() or (await el.input_value()):
                    continue
                label = ((await el.get_attribute("aria-label"))
                         or (await el.get_attribute("name")) or "")
                if ab.is_prohibited(label):
                    continue
                vk = ab.match_text_field(label.lower())
                if vk and vals.get(vk):
                    await el.fill(vals[vk])
                    filled.append(FieldFill(vk, vals[vk]))
            except Exception:
                continue
        try:
            selects = await page.query_selector_all(f"{scope} select")
        except Exception:
            selects = []
        for sel in selects:
            try:
                if not await sel.is_visible():
                    continue
                label = ((await sel.get_attribute("aria-label")) or "").lower()
                ans = ab.known_answer(label, profile)
                if ans:
                    try:
                        await sel.select_option(label=ans)
                        continue
                    except Exception:
                        pass
                req = await sel.get_attribute("required")
                if req is not None and not (await sel.input_value()):
                    missing.append(label[:50] or "dropdown question")
            except Exception:
                continue
        return missing

    async def _upload(self, page, cv_path):
        if not cv_path:
            return
        try:
            fi = await page.query_selector("input[type='file']")
            if fi:
                await fi.set_input_files(cv_path)
        except Exception:
            pass

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
        for t in ("Application sent", "application was sent", "המועמדות נשלחה",
                  "נשלחה"):
            try:
                if await page.query_selector(f"h2:has-text('{t}'), h3:has-text('{t}'), "
                                             f"div:has-text('{t}')"):
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
                await x.click()
                await page.wait_for_timeout(700)
            d = await self._find(page, DISCARD)
            if d:
                await d.click()
                await page.wait_for_timeout(400)
        except Exception:
            pass
