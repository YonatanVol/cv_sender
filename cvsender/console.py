"""The console: questions answered from the database, never invented.

Yonatan asked for an assistant that can say why a job was rejected, what is
blocking, and what to do next. It is deliberately not an AI: every answer here
is a query, so it costs nothing, is identical every time, and cannot fabricate
a statistic. An unrecognised question says so instead of guessing.

If an AI layer is ever added, it belongs on top of these handlers — they are the
part that must stay true.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

from . import today
from .db import store
from .engine import worker
from .funnel import keywords as K


def _fmt_job(c: dict) -> str:
    age = f", seen {c['age_days']}d ago" if c.get("age_days") is not None else ""
    return f"{c['score'] or '?'} {c['band']} · {c['company']} — {c['title']}{age}"


# ------------------------------- handlers ---------------------------------

def what_next(_: str = "") -> dict:
    s = today.snapshot()
    nxt = s["next"]
    if not nxt:
        return {"answer": "Nothing is waiting for you. The queue is empty — "
                          "run a search to stage more.", "data": s["counts"]}
    if nxt["kind"] == "answer":
        return {"answer": f"Answer “{nxt['question']}” — {nxt['why'].lower()}.",
                "action": {"label": "Open answers", "href": "/answers"}, "data": nxt}
    item = nxt["item"]
    return {"answer": f"{nxt['action']}: {_fmt_job(item)}. {nxt['why']}.",
            "action": {"label": nxt["action"], "href": item["url"]}, "data": nxt}


def whats_blocking(_: str = "") -> dict:
    s = today.snapshot()
    c = s["counts"]
    parts = []
    if c.get("question"):
        parts.append(f"{c['question']} waiting on a screening answer")
    if c.get("captcha"):
        parts.append(f"{c['captcha']} need you to clear a form check")
    if c.get("review"):
        parts.append(f"{c['review']} are borderline roles to approve")
    if c.get("error"):
        parts.append(f"{c['error']} failed with an error")
    if c.get("form"):
        parts.append(f"{c['form']} need the form finished by hand")
    if not parts:
        return {"answer": "Nothing is blocked.", "data": c}
    top = ", ".join(f"“{q['label']}” ({q['blocking']})" for q in s["questions"][:3])
    extra = f" The questions blocking the most: {top}." if s["questions"] else ""
    return {"answer": "; ".join(parts) + "." + extra, "data": c}


def why_nothing_sent(_: str = "") -> dict:
    s = today.snapshot()
    if s["sent_today"]:
        return {"answer": f"{s['sent_today']} went out today.", "data": s["goal"]}
    reasons = []
    if not s["counts"].get("ready"):
        reasons.append("nothing is in the ready state — every queued posting still "
                       "needs a person (a form check, an answer, or an approval)")
    if s["linkedin_left"] <= 0:
        reasons.append(f"the LinkedIn daily cap of {worker.linkedin_daily_cap()} is used up")
    for p in s["health"]["problems"]:
        reasons.append(f"{p['check']}: {p['detail']}")
    if not reasons:
        reasons.append("no send has been started today")
    return {"answer": "Nothing sent today because " + "; ".join(reasons) + ".",
            "data": {"counts": s["counts"], "linkedin_left": s["linkedin_left"]}}


def what_failed(_: str = "") -> dict:
    items = [i for i in store.assist_queue(1000)
             if (i.get("block_kind") == "error" or i.get("state") == "failed")]
    if not items:
        return {"answer": "Nothing has failed.", "data": []}
    rows = [{"company": i["company"], "title": i["title"], "reason": i.get("reason") or ""}
            for i in items[:8]]
    listed = "; ".join(f"{r['company']}: {r['reason'][:60]}" for r in rows[:4])
    return {"answer": f"{len(items)} failed. {listed}", "data": rows}


def show_jobs(question: str) -> dict:
    """'show me C++ and systems jobs' — filtered from the live queue."""
    q = (question or "").lower()
    def mentions(word: str) -> bool:
        """Whole words only: a bare 'c' must not match every question."""
        w = word.strip().lower()
        return bool(w) and re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", q) is not None

    wanted = [name for name, needles in K.SKILL_SIGNALS
              if any(mentions(n) for n in needles) or mentions(name.split(" /")[0])]
    queue = store.assist_queue(1000)
    cards = [today.card(i) for i in queue]
    if wanted:
        def matches(card: dict, skill: str) -> bool:
            if any(skill == r.get("label") for r in card.get("reasons") or []):
                return True                      # the score already credited it
            needles = dict(K.SKILL_SIGNALS).get(skill, [])
            title = (card.get("title") or "").lower()
            return any(n.strip() and re.search(
                rf"(?<![a-z0-9]){re.escape(n.strip().lower())}(?![a-z0-9])", title)
                for n in needles)

        picked = [c for c in cards if any(matches(c, w) for w in wanted)]
        label = " and ".join(wanted)
    else:
        picked = cards
        label = "the queue"
    picked.sort(key=lambda c: -(c["score"] or 0))
    if not picked:
        where = "matching that" if wanted else "in the queue"
        return {"answer": f"Nothing {where} right now.", "data": []}
    lines = [_fmt_job(c) for c in picked[:6]]
    return {"answer": f"{len(picked)} in {label}: " + " | ".join(lines), "data": picked[:20]}


def why_this_score(question: str) -> dict:
    m = re.search(r"#?(\d{1,6})", question or "")
    if not m:
        return {"answer": "Which posting? Ask with its number, e.g. “why 412”.", "data": {}}
    item = store.get_item(int(m.group(1)))
    if not item:
        return {"answer": f"No posting #{m.group(1)}.", "data": {}}
    c = today.card(item)
    if not c["reasons"]:
        return {"answer": f"{c['company']} — {c['title']}: scored {c['score']}, "
                          "but this one was staged before scores carried their reasons.",
                "data": c}
    detail = ", ".join(f"{r['label']} {r['points']:+d}" for r in c["reasons"])
    return {"answer": f"{c['company']} — {c['title']}: {c['score']} {c['band']} "
                      f"(50 base, {detail}).", "data": c}


def which_cv(question: str) -> dict:
    from . import cv_tailor
    m = re.search(r"#?(\d{1,6})", question or "")
    if m and store.get_item(int(m.group(1))):
        item = store.get_item(int(m.group(1)))
        path, name = cv_tailor.cv_for(item.get("title") or "")
        return {"answer": f"{item['company']} — {item['title']}: the “{name or 'general'}” CV.",
                "data": {"variant": name, "path": path}}
    variants = store.list_cv_variants()
    names = ", ".join(v["name"] for v in variants) or "none"
    return {"answer": f"CV versions: {names}. Ask with a posting number to see which "
                      "one it would send.", "data": variants}


def system_status(_: str = "") -> dict:
    s = today.snapshot()
    if s["health"]["state"] == "ok":
        sched = s["scheduler"]
        return {"answer": f"Everything is healthy. Next staging {sched['next_staging_at']}, "
                          f"{s['counts']['total']} in the queue, "
                          f"{s['linkedin_left']} LinkedIn sends left today.",
                "data": s["health"]}
    problems = "; ".join(f"{p['check']}: {p['detail']}" for p in s["health"]["problems"])
    return {"answer": f"{s['health']['state'].upper()} — {problems}", "data": s["health"]}


def queue_freshness(_: str = "") -> dict:
    f = store.queue_age_report()
    return {"answer": f"{f['total']} postings: {f['fresh_7d']} seen in the last week, "
                      f"{f['stale_14d']} within a month, {f['old_30d']} older. "
                      f"{f['unverified_old']} old ones still unverified.", "data": f}


# ------------------------------- routing ----------------------------------

QUESTIONS: list[tuple[str, str, Callable[[str], dict]]] = [
    ("next", "What should I do next?", what_next),
    ("blocking", "What is blocking applications?", whats_blocking),
    ("nothing_sent", "Why was nothing sent today?", why_nothing_sent),
    ("failed", "What failed?", what_failed),
    ("jobs", "Show me the best jobs", show_jobs),
    ("score", "Why did a job score that?", why_this_score),
    ("cv", "Which CV would you send?", which_cv),
    ("status", "Is everything working?", system_status),
    ("freshness", "How fresh is the queue?", queue_freshness),
]
_BY_KEY = {key: fn for key, _, fn in QUESTIONS}

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(next|what should i|what now|start|begin)\b", re.I), "next"),
    (re.compile(r"\b(block|blocked|blocking|stuck|waiting)\b", re.I), "blocking"),
    (re.compile(r"\b(nothing sent|why.*not sent|no sends?|didn'?t send)\b", re.I), "nothing_sent"),
    (re.compile(r"\b(fail|failed|failure|error|broke)\b", re.I), "failed"),
    (re.compile(r"\b(score|why.*\d+|rank|rating)\b", re.I), "score"),
    (re.compile(r"\b(cv|resume|variant)\b", re.I), "cv"),
    (re.compile(r"\b(status|health|working|broken|doctor)\b", re.I), "status"),
    (re.compile(r"\b(fresh|stale|old|age|dead)\b", re.I), "freshness"),
    # Asking to SEE jobs, not merely mentioning the word: "will I get this job?"
    # is a question about the future, which this console cannot answer.
    (re.compile(r"\b(show|find|list|which|best|open)\b.{0,20}\b(job|jobs|role|position)\b",
                re.I), "jobs"),
    (re.compile(r"(?<![a-z])(c\+\+|cpp|backend|embedded|frontend|fullstack|full.stack|"
                r"python|java|linux|algorithms?|devops|qa|sql|data)(?![a-z])", re.I), "jobs"),
]


def ask(question: str) -> dict:
    """Answer one question. Unrecognised means unrecognised — never a guess."""
    text = (question or "").strip()
    if not text:
        return what_next("")
    if text in _BY_KEY:
        return _BY_KEY[text](text)
    for pattern, key in _PATTERNS:
        if pattern.search(text):
            return _BY_KEY[key](text)
    return {"answer": "I do not have an answer for that. I can only report what is in "
                      "the database — try one of the buttons.",
            "unknown": True,
            "data": {"known": [label for _, label, _ in QUESTIONS]}}
