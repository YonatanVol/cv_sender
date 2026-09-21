"""What to do now — one object, built from the database.

The queue answers "what is there"; this answers "what should Yonatan do in the
next five minutes". It never estimates or invents: every number here is a query,
so the screen and the console can only ever repeat what the database says.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from . import health, scheduler
from .db import store
from .engine import worker

DEFAULT_GOAL = 3          # applications finished per active day


def _goal() -> int:
    try:
        return max(1, int(store.get_setting("today.goal") or DEFAULT_GOAL))
    except (TypeError, ValueError):
        return DEFAULT_GOAL


def _score_of(item: dict) -> dict:
    try:
        return json.loads(item.get("score_json") or "{}") or {}
    except (TypeError, ValueError):
        return {}


def _age_days(item: dict, now: float) -> Optional[int]:
    seen = item.get("posted_at") or item.get("first_seen_at") or item.get("created_at")
    return int((now - seen) / 86400) if seen else None


def _bucket(item: dict) -> str:
    if item.get("state") == "ready":
        return "ready"
    kind = item.get("block_kind") or ""
    if kind in ("captcha", "question", "review", "error"):
        return kind
    reason = (item.get("reason") or "").lower()
    if "captcha" in reason:
        return "captcha"
    if "answer" in reason or "question" in reason:
        return "question"
    if item.get("state") == "failed":
        return "error"
    return "form"


def card(item: dict, now: Optional[float] = None) -> dict:
    """One posting, as a screen shows it: what it is, how good, and why."""
    now = now if now is not None else time.time()
    s = _score_of(item)
    return {
        "id": item["id"], "company": item.get("company") or "", "title": item.get("title") or "",
        "channel": item.get("channel"), "url": item.get("apply_url") or item.get("url"),
        "state": item.get("state"),
        # Rows staged before block_kind existed still carry their reason, so the
        # card must not claim "ready" for something that is not.
        "block": _bucket(item),
        "score": s.get("score", item.get("score")), "band": s.get("band", ""),
        "why": s.get("explain", ""), "reasons": s.get("reasons", []),
        "age_days": _age_days(item, now), "liveness": item.get("liveness") or "unknown",
        "questions": len((json.loads(item.get("result_json") or "{}") or {}).get("questions") or []),
        "cv_attached": bool((json.loads(item.get("result_json") or "{}") or {}).get("cv_attached")),
    }


def next_action(queue: list[dict], gaps: list[dict], now: float) -> Optional[dict]:
    """The single most valuable next move, and why it is that one.

    Order: finish something already prepared, then unblock many postings with
    one answer, then the best fresh posting. Nothing is invented — if the queue
    is empty this returns None and the screen says so.
    """
    ready = [i for i in queue if i.get("state") == "ready"]
    if ready:
        best = max(ready, key=lambda i: (_score_of(i).get("score") or 0))
        c = card(best, now)
        return {"kind": "send", "item": c,
                "why": f"Already filled and ready — {c['band'] or 'a match'} at {c['company']}",
                "action": "Open & send"}
    if gaps:
        top = gaps[0]
        return {"kind": "answer", "question": top["label"], "blocking": top["blocking"],
                "why": f"One answer unblocks {top['blocking']} application"
                       f"{'s' if top['blocking'] != 1 else ''}",
                "action": "Answer it"}
    due = store.followups_due(now)
    if due and not [i for i in queue if _bucket(i) == "question"]:
        a = due[0]
        days = int((now - (a.get("sent_at") or now)) / 86400)
        return {"kind": "followup", "application": {"id": a["id"], "company": a["company"],
                                                    "title": a["title"], "days": days},
                "why": f"{days} days with no answer from {a['company']}",
                "action": "Send a follow-up"}
    finishable = [i for i in queue if _bucket(i) in ("captcha", "form")]
    if finishable:
        best = max(finishable, key=lambda i: (_score_of(i).get("score") or 0))
        c = card(best, now)
        return {"kind": "finish", "item": c,
                "why": f"Filled with your CV — it only needs you to clear the form"
                       f" ({c['band'] or 'match'})",
                "action": "Fill it for me"}
    return None


def snapshot(limit: int = 3) -> dict:
    """Everything the Today screen shows, in one object."""
    now = time.time()
    queue = store.assist_queue(limit=1000)
    gaps = store.answer_gaps(limit=50)
    buckets: dict[str, list[dict]] = {}
    for item in queue:
        buckets.setdefault(_bucket(item), []).append(item)
    scored = sorted(queue, key=lambda i: -(_score_of(i).get("score") or 0))
    rep = health.report()
    done = store.sent_today()
    goal = _goal()
    return {
        "at": now,
        "goal": {"target": goal, "done": done, "remaining": max(0, goal - done),
                 "met": done >= goal},
        "next": next_action(queue, gaps, now),
        "best_jobs": [card(i, now) for i in scored[:limit]],
        "counts": {k: len(v) for k, v in sorted(buckets.items())} | {"total": len(queue)},
        "questions": [{"label": g["label"], "blocking": g["blocking"]} for g in gaps[:5]],
        "questions_total": len(gaps),
        "sent_today": done,
        "linkedin_left": worker.linkedin_cap_left(),
        "applications": len(store.recent_applications(limit=1000)),
        "funnel": store.funnel_counts(),
        "followups_due": [{"id": a["id"], "company": a["company"], "title": a["title"],
                           "days": int((now - (a.get("sent_at") or now)) / 86400)}
                          for a in store.followups_due(now)[:5]],
        "freshness": store.queue_age_report(),
        "health": {"state": rep["state"],
                   "problems": [{"check": c["check"], "detail": c["detail"], "fix": c["fix"]}
                                for c in rep["checks"] if c["state"] != "ok"]},
        "scheduler": scheduler.status(),
    }
