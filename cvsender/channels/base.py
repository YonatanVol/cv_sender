"""The channel contract. Every channel (ATS, LinkedIn, Email) implements this
so the engine orchestrates them uniformly under the auto-fill + 1-click-confirm
model. prepare() NEVER performs the irreversible action; send() is the only
method that does, and the engine calls it exclusively after a human confirm.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


def content_hash(company: str, title: str, jd: str = "") -> str:
    """Cross-channel dup key: same role reposted under a new id / other board."""
    norm = f"{(company or '').strip().lower()}|{(title or '').strip().lower()}|{(jd or '')[:400].strip().lower()}"
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


@dataclass
class Job:
    channel: str
    company: str
    external_id: str
    title: str
    location: str = ""
    url: str = ""
    apply_url: str = ""
    remote: bool = False
    description: str = ""
    posted_at: Optional[float] = None      # epoch seconds, when the board says
    raw: dict = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        return f"{self.channel}:{(self.company or '').strip().lower()}:{self.external_id}"

    @property
    def identity(self) -> str:
        """One real position, whatever board it came from.

        dedupe_key is channel-prefixed, so the same job listed on LinkedIn and
        on Greenhouse was structurally two cards. This key is not: it is the
        company, the role and the place, normalised.
        """
        return job_identity(self.company, self.title, self.location)

    @property
    def content_hash(self) -> str:
        return content_hash(self.company, self.title, self.description)


@dataclass
class Question:
    label: str                      # original language (e.g. Hebrew)
    kind: str = "text"              # text | select | radio | checkbox | file
    options: list[str] = field(default_factory=list)
    required: bool = True
    suggested: Optional[str] = None
    answered: bool = False
    reason: str = ""                # why unanswered / blocked


@dataclass
class FieldFill:
    label: str
    value: str
    kind: str = "text"
    source: str = "profile"        # profile | answer_bank | default


# Verdicts a prepare() may return.
READY = "ready"
NEEDS_INPUT = "needs_input"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class PrepareResult:
    state: str                                  # READY | NEEDS_INPUT | FAILED | SKIPPED
    filled: list[FieldFill] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)   # unanswered -> needs_input
    answers: dict = field(default_factory=dict)               # durable, for re-fill on send
    reason: str = ""
    screenshot: Optional[str] = None
    cv_attached: bool = False


@dataclass
class SendHandle:
    """DURABLE — fully serializable, survives crash + long human review delay."""
    dedupe_key: str
    channel: str
    apply_url: str
    company: str = ""
    title: str = ""
    answers: dict = field(default_factory=dict)
    cv_path: str = ""
    cv_sha256: str = ""


@dataclass
class ConfirmationEvidence:
    method: str                     # network | dom | url | message_id
    detail: str = ""
    http_status: Optional[int] = None
    matched: Optional[str] = None   # selector / url
    at: float = 0.0

    def to_json(self) -> str:
        import json
        return json.dumps(self.__dict__)


# Send outcomes.
SENT = "sent"
SENT_UNVERIFIED = "sent_unverified"
SEND_FAILED = "failed"
SEND_NEEDS_INPUT = "needs_input"


@dataclass
class SendResult:
    state: str                                  # SENT | SENT_UNVERIFIED | SEND_FAILED | SEND_NEEDS_INPUT
    evidence: Optional[ConfirmationEvidence] = None
    reason: str = ""
    screenshot: Optional[str] = None


@runtime_checkable
class ChannelAdapter(Protocol):
    channel: str

    async def discover(self, spec: dict) -> list[Job]:
        ...

    async def prepare(self, ctx: Any, job: Job, profile: dict, cv_path: str,
                      cancel: Any) -> PrepareResult:
        ...

    async def send(self, ctx: Any, handle: SendHandle, cancel: Any) -> SendResult:
        ...

_IDENT_DROP = re.compile(r"\b(inc|ltd|limited|llc|corp|corporation|gmbh|co|"
                         r"technologies|technology|labs|group|israel|il)\b", re.I)
# Boards write the same employer as "comigo", "Comigo.io" and "comigo-ai".
_IDENT_TLD = re.compile(r"[.\-](io|ai|com|net|org|co|tech|app|dev)$", re.I)
_IDENT_NOISE = re.compile(r"[^a-z0-9\u0590-\u05ea]+")
_TITLE_NOISE = re.compile(
    r"\b(m/f/d|f/m/d|all genders|remote|hybrid|on-?site|full[- ]time|part[- ]time|"
    r"contract|temporary|maternity cover|tel aviv|israel|\d{3,})\b", re.I)


def _norm(text: str, extra=None) -> str:
    t = (text or "").lower()
    if extra is not None:
        t = extra.sub(" ", t)
    t = _IDENT_DROP.sub(" ", t)
    return _IDENT_NOISE.sub("-", t).strip("-")


def job_identity(company: str, title: str, location: str = "") -> str:
    """company|role|city — stable across boards, so duplicates collapse."""
    city = (location or "").split(",")[0]
    name = _IDENT_TLD.sub("", _norm(company))
    return f"{name}|{_norm(title, _TITLE_NOISE)}|{_norm(city)}"

