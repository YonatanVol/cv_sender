"""LinkedIn Easy Apply detection (2026-09 SDUI flow) and send verification."""
import asyncio

from cvsender.channels.linkedin import LinkedInChannel


class El:
    def __init__(self, visible=True): self._v = visible
    async def is_visible(self): return self._v
    async def is_enabled(self): return True
    async def scroll_into_view_if_needed(self, timeout=0): pass
    async def click(self, timeout=0): pass


class Page:
    """Answers query_selector from a {substring-of-selector: element} map."""
    def __init__(self, present): self.present, self.asked = present, []
    async def query_selector(self, sel):
        self.asked.append(sel)
        for key, el in self.present.items():
            if key in sel:
                return el
        return None
    async def wait_for_timeout(self, ms): pass


def run(coro): return asyncio.run(coro)


def test_new_sdui_easy_apply_link_is_detected():
    page = Page({"openSDUIApplyFlow": El()})
    assert run(LinkedInChannel()._open_modal(page)) is True
    assert "openSDUIApplyFlow" in page.asked[0]          # tried first


def test_hebrew_labelled_link_is_detected():
    assert run(LinkedInChannel()._open_modal(Page({"הגשת מועמדות בקלות": El()}))) is True


def test_external_apply_page_is_not_easy_apply():
    assert run(LinkedInChannel()._open_modal(Page({}))) is False


def test_sent_requires_submit_button_gone():
    # confirmation-looking text present, but the Submit button is still there
    page = Page({"Submit application": El(), "Application sent": El()})
    assert run(LinkedInChannel()._sent(page)) is False


def test_sent_true_only_with_visible_confirmation():
    assert run(LinkedInChannel()._sent(Page({"Application sent": El()}))) is True
    assert run(LinkedInChannel()._sent(Page({"Application sent": El(visible=False)}))) is False
    assert run(LinkedInChannel()._sent(Page({}))) is False


def test_cards_to_jobs_parses_virtualised_cards():
    from cvsender.channels.linkedin import cards_to_jobs
    rows = [
        {"id": "4465241015", "lines": ["Junior Systems Implementer", "Junior Systems Implementer with verification",
                                       "Comigo.io", "Petah Tikva, Center District, Israel (On-site)", "16 minutes ago"]},
        {"id": "4465235111", "lines": ["Hebrew Transcriber (Freelance)", "DatoviaPlayHouse", "Tel Aviv-Yafo (Remote)"]},
        {"id": "not-a-number", "lines": ["x"]},
        {"id": "123", "lines": []},
    ]
    jobs = cards_to_jobs(rows, "Israel", "junior developer")
    assert [j.external_id for j in jobs] == ["4465241015", "4465235111"]
    assert jobs[0].title == "Junior Systems Implementer" and jobs[0].company == "Comigo.io"
    assert jobs[0].location.startswith("Petah Tikva")
    assert jobs[1].company == "DatoviaPlayHouse"
    assert jobs[0].apply_url == "https://www.linkedin.com/jobs/view/4465241015/"
    assert jobs[0].dedupe_key == "linkedin:comigo.io:4465241015"


# --------------------- the 2026-09-22 SDUI apply form -----------------------
# Measured on a real posting: the modal has no role="dialog" and no
# .jobs-easy-apply-content, so the old selector pair matched 0 controls and every
# screening question was reported as "required field flagged". 66 postings were
# stuck behind that.

class SduiEl:
    """One control of the SDUI apply form."""
    def __init__(self, field): self.field, self.filled = field, None
    async def is_visible(self): return True
    async def evaluate(self, js): return dict(self.field)
    async def select_option(self, **kw): self.filled = kw
    async def fill(self, v): self.filled = v


class SduiPage:
    """Only selectors that reach the SDUI form find anything — exactly like the
    real page, where role=dialog and .jobs-easy-apply-content do not exist."""
    HOOKS = ("easyApplyFormElement", "fb-dash-form-element",
             "jobs-easy-apply-form-section__grouping")

    def __init__(self, fields): self.fields = fields
    async def query_selector_all(self, sel):
        if not any(h in sel for h in self.HOOKS):
            return []
        return [SduiEl(f) for f in self.fields]


def _field(**kw):
    base = {"tag": "SELECT", "type": "select-one", "id": "x", "name": "",
            "required": True, "value": "Select an option", "checked": False,
            "label": "Are you currently a student?", "own": "",
            "options": ["Select an option", "Yes", "No"]}
    base.update(kw)
    return base


def test_sdui_form_controls_are_found():
    fields = run(LinkedInChannel()._read_fields(SduiPage([_field()])))
    assert [f["label"] for f in fields] == ["Are you currently a student?"]


def test_placeholder_select_counts_as_unanswered():
    from cvsender.channels.linkedin import is_placeholder
    assert is_placeholder("Select an option") and is_placeholder("בחר אפשרות")
    assert not is_placeholder("Yes")
    f = run(LinkedInChannel()._read_fields(SduiPage([_field()])))[0]
    assert f["value"] == ""          # so _fill_step asks instead of skipping


def test_wrapper_div_is_not_read_as_a_control():
    # [id*=easyApplyFormElement] also matches the wrapper <div>; it is not a field
    fields = run(LinkedInChannel()._read_fields(SduiPage([
        _field(tag="DIV", type="", label="Select an option Yes No"), _field()])))
    assert len(fields) == 1 and fields[0]["tag"] == "SELECT"


def test_sdui_question_reaches_the_human_as_a_question():
    """The whole point: a real question, not 'required field flagged'."""
    asked = []
    missing = run(LinkedInChannel()._fill_step(
        SduiPage([_field(label="What is your GPA?", options=[])]), {}, [], asked))
    assert [q.label for q in missing] == ["What is your GPA?"]


# ------------------------- radio groups ask a question ----------------------
# Measured: LinkedIn renders a yes/no question as a <fieldset> whose <legend> is
# the question, with one <label for=…> per choice. Reading the choice label as
# the question turned 13 postings into 'Answer 1 question: Yes'.

def test_radio_group_is_labelled_with_its_question():
    q = _field(tag="INPUT", type="radio", id="q-0", name="q",
               label="Are you comfortable working in an onsite setting?",
               own="Yes", value="Yes", options=[])
    n = dict(q, id="q-1", own="No", value="No")
    fields = run(LinkedInChannel()._read_fields(SduiPage([q, n])))
    assert len(fields) == 1                       # one question, not two
    group = fields[0]
    assert group["kind"] == "radio"
    assert group["label"] == "Are you comfortable working in an onsite setting?"
    assert group["options"] == ["Yes", "No"]


def test_field_reader_asks_the_fieldset_before_the_choice_label():
    """The JS half of the same fix.

    _FIELD_JS runs in the page, so it cannot be exercised here; this asserts the
    ordering that makes it correct — a radio consults its group first. Verified
    live on 2026-09-22 against linkedin.com/jobs/view/4464764797: the question
    read 'Are you comfortable working in an onsite setting?' where it previously
    read 'Yes'.
    """
    from cvsender.channels.linkedin import _FIELD_JS
    radio_branch = _FIELD_JS.index('=== "radio"')
    for_branch = _FIELD_JS.index('label[for=', radio_branch)
    assert radio_branch < for_branch          # group wins for a radio


# ------------------- 2026-10-05: the native <dialog> form -------------------
# LinkedIn moved the apply form into <dialog open> with hashed class names and
# React ids ("_r_7_"). Every hook we had matched nothing: 23 of 28 postings
# came back "too many steps", with nothing filled and no screenshot.

class DialogPage(SduiPage):
    """Answers only selectors anchored on the native dialog."""
    HOOKS = ("dialog[open]",)


def test_controls_inside_a_native_dialog_are_found():
    fields = run(LinkedInChannel()._read_fields(DialogPage([
        _field(label="How many years of work experience do you have with C++?",
               tag="INPUT", type="text", value="", options=[])])))
    assert [f["label"] for f in fields] == [
        "How many years of work experience do you have with C++?"]


class Btn:
    def __init__(self, page, text): self.page, self.text = page, text
    async def is_visible(self): return True
    async def is_enabled(self): return True
    async def scroll_into_view_if_needed(self, timeout=0): pass
    async def click(self, timeout=0): self.page.press(self.text)


class StepEl(SduiEl):
    def __init__(self, field, page): super().__init__(field); self.page = page
    async def fill(self, v): self.field["value"] = v
    async def select_option(self, **kw): self.field["value"] = next(iter(kw.values()))


class FormPage:
    """A multi-step form that refuses Next while a required field is empty —
    the way the real one behaves, judged by native validity."""

    def __init__(self, steps):
        self.steps, self.i, self.submitted = steps, 0, False

    def current(self): return self.steps[self.i]

    def press(self, text):
        if any(f["required"] and not f["value"] for f in self.current()):
            return                                   # refused: stay on this step
        if self.i < len(self.steps) - 1:
            self.i += 1

    async def query_selector_all(self, sel):
        if "dialog[open]" not in sel:
            return []
        return [StepEl(f, self) for f in self.current()]

    async def query_selector(self, sel):
        last = self.i == len(self.steps) - 1
        if last and "Submit application" in sel:
            return Btn(self, "submit")
        if not last and ("'Next'" in sel or "Next" in sel):
            return Btn(self, "next")
        return None

    async def evaluate(self, js):                    # _REFUSED_JS
        return any(f["required"] and not f["value"] for f in self.current())

    async def wait_for_timeout(self, ms): pass
    async def screenshot(self, **kw): pass


class NoCancel:
    def check(self): pass


def _q(label, value="", kind_tag=("INPUT", "text"), options=()):
    return _field(label=label, tag=kind_tag[0], type=kind_tag[1], value=value,
                  options=list(options), required=True)


def test_a_new_step_we_can_answer_is_filled_not_abandoned(tmp_path, monkeypatch):
    """The trap: a fresh step's empty required fields are 'invalid' to the
    browser too. Treating that as refused would stop at every step."""
    import cvsender.config as config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    from cvsender.db import store
    migrate()
    store.learn_answer("Are you currently a student?", "Yes")

    page = FormPage([
        [_q("Mobile phone number", value="528701670")],
        [_q("Are you currently a student?", kind_tag=("SELECT", "select-one"),
            options=["Yes", "No"])],
        [],                                           # review
    ])
    res = run(LinkedInChannel()._walk(page, {}, "", NoCancel(), submit=False))
    assert res.state == "ready", res.reason
    assert page.steps[1][0]["value"] == "Yes"


def test_a_refused_step_comes_back_as_its_questions(tmp_path, monkeypatch):
    import cvsender.config as config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    migrate()
    page = FormPage([
        [_q("Mobile phone number", value="528701670")],
        [_q("How many years of work experience do you have with C++?")],
        [],
    ])
    res = run(LinkedInChannel()._walk(page, {}, "", NoCancel(), submit=False))
    assert res.state == "needs_input"
    assert [q.label for q in res.questions] == [
        "How many years of work experience do you have with C++?"]
    assert "too many steps" not in (res.reason or "")


# ---------------- 2026-10-05: yes/no is the ARIA radio pattern --------------
# <fieldset role="radiogroup"> with no legend; each choice is a visible
# <div role="radio" aria-checked aria-label="<the question>">Yes</div>; the
# native input inside is 0x0. Read by visibility alone, the question vanished.

class AriaRadio:
    def __init__(self, info): self.info = info
    async def is_visible(self): return True
    async def evaluate(self, js): return dict(self.info)


class AriaPage:
    def __init__(self, radios): self.radios = radios
    async def query_selector_all(self, sel):
        if "[role='radio']" in sel:
            return [AriaRadio(r) for r in self.radios]
        return []                         # the native inputs are invisible


def _choice(own, checked=False, q="Are you currently a student?", key="radio-group-_r_1p_"):
    return {"question": q, "own": own, "checked": checked, "required": True, "key": key}


def test_an_aria_radio_group_reads_as_one_question_with_its_choices():
    fields = run(LinkedInChannel()._read_fields(AriaPage([_choice("Yes"), _choice("No")])))
    assert len(fields) == 1
    g = fields[0]
    assert g["kind"] == "radio" and g["label"] == "Are you currently a student?"
    assert g["options"] == ["Yes", "No"] and g["required"] and g["value"] == ""


def test_an_answered_aria_group_carries_its_choice():
    fields = run(LinkedInChannel()._read_fields(AriaPage([_choice("Yes"), _choice("No", True)])))
    assert fields[0]["value"] == "No"


def test_two_aria_groups_stay_two_questions():
    fields = run(LinkedInChannel()._read_fields(AriaPage([
        _choice("Yes"), _choice("No"),
        _choice("Yes", q="Do you hold a BSc?", key="radio-group-_r_2a_"),
        _choice("No", q="Do you hold a BSc?", key="radio-group-_r_2a_")])))
    assert sorted(f["label"] for f in fields) == ["Are you currently a student?",
                                                   "Do you hold a BSc?"]
