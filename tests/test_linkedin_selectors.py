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
