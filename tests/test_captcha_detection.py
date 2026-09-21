"""A reCAPTCHA badge is not a challenge.

Every Greenhouse page carries the invisible reCAPTCHA v3 badge. Treating it as
a blocker parked 137 fully-filled applications (CV attached, no open questions)
behind something no human is ever asked to solve. These fixtures are the real
markup of each case.
"""
import asyncio

import pytest
from playwright.async_api import async_playwright

from cvsender.channels import atsform

BADGE = """<html><body><form><input name=email></form>
  <div class="grecaptcha-badge" style="width:256px;height:60px;position:fixed">
    <iframe title="reCAPTCHA" src="https://www.recaptcha.net/recaptcha/enterprise/anchor?ar=1"
            style="width:256px;height:60px"></iframe>
  </div></body></html>"""

INVISIBLE_WIDGET = """<html><body><form><input name=email>
  <div class="g-recaptcha" data-size="invisible" data-sitekey="k"
       style="width:300px;height:80px"></div></form></body></html>"""

CHECKBOX_WIDGET = """<html><body><form><input name=email>
  <div class="g-recaptcha" data-sitekey="k" style="width:304px;height:78px">
    <iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor"
            style="width:304px;height:78px"></iframe>
  </div></form></body></html>"""

HCAPTCHA = """<html><body><form><input name=email>
  <div class="h-captcha" data-sitekey="k" style="width:302px;height:76px">
    <iframe src="https://newassets.hcaptcha.com/captcha/v1/frame"
            style="width:302px;height:76px"></iframe>
  </div></form></body></html>"""

TURNSTILE = """<html><body><form><input name=email>
  <div class="cf-turnstile" data-sitekey="k" style="width:300px;height:65px">
    <iframe src="https://challenges.cloudflare.com/turnstile/v0/frame"
            style="width:300px;height:65px"></iframe>
  </div></form></body></html>"""

OPEN_CHALLENGE = """<html><body><form><input name=email></form>
  <div class="grecaptcha-badge" style="width:256px;height:60px">
    <iframe title="reCAPTCHA" src="https://www.recaptcha.net/recaptcha/enterprise/anchor"
            style="width:256px;height:60px"></iframe></div>
  <iframe src="https://www.google.com/recaptcha/api2/bframe?k=x"
          style="width:400px;height:580px"></iframe></body></html>"""

NOTHING = """<html><body><form><input name=email></form></body></html>"""


def kind_of(markup: str) -> str:
    async def go():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(markup)
            out = await atsform.captcha_kind(page)
            await browser.close()
            return out
    return asyncio.run(go())


@pytest.mark.parametrize("name,markup", [
    ("no captcha at all", NOTHING),
    ("invisible v3 badge (every Greenhouse page)", BADGE),
    ("invisible widget", INVISIBLE_WIDGET),
])
def test_nothing_a_human_must_solve(name, markup):
    assert kind_of(markup) == "", name


@pytest.mark.parametrize("name,markup", [
    ("reCAPTCHA checkbox", CHECKBOX_WIDGET),
    ("hCaptcha", HCAPTCHA),
    ("Cloudflare Turnstile", TURNSTILE),
    ("open challenge popup", OPEN_CHALLENGE),
])
def test_real_challenges_still_block(name, markup):
    # which label ('widget' / 'challenge') matters less than the verdict: a
    # human has to act, so the item must not be offered as ready to send.
    assert kind_of(markup) in ("widget", "challenge"), name


@pytest.mark.parametrize("markup,blocks", [(BADGE, False), (CHECKBOX_WIDGET, True)])
def test_greenhouse_uses_the_same_definition(markup, blocks):
    """Call it for real: a docstring check would not have caught the missing
    import that made this path raise NameError."""
    from cvsender.channels import greenhouse

    async def go():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(markup)
            out = await greenhouse._has_captcha(page)
            await browser.close()
            return out
    assert asyncio.run(go()) is blocks


# ---- the form must be where we say it is ----

FORM_WITH_LABELS = """<html><body><form>
  <label for="q1">How many years of experience do you have with Go?</label>
  <input id="q1" required>
  <div class="field"><label>Are you available full-time?</label>
    <select required><option></option><option>Yes</option><option>No</option></select></div>
  <input id="q3" aria-label="What is your GPA?" required>
  <input type="file" required>
  <input type="hidden" required value="">
  <input id="done" required value="already filled">
</form></body></html>"""


def test_question_labels_are_what_a_human_reads():
    """They used to come out as 'question_67972490 are you legally authorized…'
    and 'country country*', which is useless on the answers page."""
    import asyncio
    from cvsender.channels import atsform

    async def go():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(FORM_WITH_LABELS)
            out = await atsform.required_unfilled(page)
            await browser.close()
            return out
    questions = asyncio.run(go())
    labels = [q.label for q in questions]
    assert "How many years of experience do you have with Go?" in labels
    assert "Are you available full-time?" in labels
    assert "What is your GPA?" in labels
    assert not any("already filled" in l for l in labels)     # answered already
    assert len(questions) == 3                                 # file/hidden skipped
    choice = next(q for q in questions if q.label.startswith("Are you"))
    assert choice.kind == "select" and choice.options == ["Yes", "No"]
