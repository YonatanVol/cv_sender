"""The prepare and send pipelines (async). Run inside a dedicated worker thread
by the RunManager, with a cancel token checked between items and inside waits."""
from __future__ import annotations

import json
import time

from .. import config
from ..channels.base import (Job, READY, NEEDS_INPUT, FAILED, SKIPPED, SENT,
                             SENT_UNVERIFIED, SendHandle)
from ..channels.registry import build_adapters
from ..core.cancel import Cancelled
from ..db import store
from ..funnel.scoring import score_job
from .session import session


def _emit(run_id, type, message="", item_id=None, level="info", data=None):
    store.add_event(run_id, type, message, item_id=item_id, level=level, data=data)


def _job_from_item(it: dict) -> Job:
    return Job(channel=it["channel"], company=it.get("company") or "",
              external_id="", title=it.get("title") or "",
              location=it.get("location") or "", url=it.get("url") or "",
              apply_url=it.get("apply_url") or "")


ATS_CHANNELS = {"greenhouse", "lever", "ashby", "comeet"}


async def run_prepare(run_id: int, options: dict, cancel) -> None:
    """PREPARE phase: discover -> score -> dedupe -> fill each (never sends).
    ATS channels run in a fast ephemeral browser; LinkedIn runs in the persistent
    logged-in context."""
    cap = int(options.get("cap", 20))
    profile = store.get_profile()
    if not profile or not profile.get("email"):
        store.update_run(run_id, status="error",
                         message="Set up your profile (name, email) first.",
                         finished_at=time.time())
        _emit(run_id, "run.error", "profile incomplete", level="error")
        return
    cv_path = profile.get("cv_path") or ""
    enabled = set(options.get("channels", ["greenhouse"]))
    remaining = cap

    try:
        if enabled & ATS_CHANNELS:
            remaining = await _prepare_ats(run_id, options, cancel, remaining,
                                           profile, cv_path,
                                           list(enabled & ATS_CHANNELS))
        if "linkedin" in enabled and remaining > 0:
            await _prepare_linkedin(run_id, options, cancel, remaining, profile,
                                    cv_path)
    except Cancelled:
        raise

    counts = store.item_counts(run_id)
    ready, ni = counts.get("ready", 0), counts.get("needs_input", 0)
    status = "awaiting_confirm" if (ready or ni) else "done"
    store.update_run(run_id, status=status, phase="send",
                     message=f"Prepared: {ready} ready · {ni} need input · "
                             f"{counts.get('failed', 0)} failed",
                     finished_at=(time.time() if status == "done" else None))
    _emit(run_id, "run.state", status, data={"status": status, "counts": counts})


async def _prepare_ats(run_id, options, cancel, cap, profile, cv_path,
                       channels) -> int:
    geography = options.get("geography", "israel_remote")
    strictness = options.get("strictness", "balanced")
    adapters = build_adapters({**options, "channels": channels})

    _emit(run_id, "phase", "Discovering jobs…")
    spec: dict = {**options, "_cancel": cancel}
    all_jobs: list[Job] = []
    for adapter in adapters.values():
        cancel.check()
        all_jobs.extend(await adapter.discover(spec))
    for key, h in (spec.get("_health") or {}).items():
        _emit(run_id, "source.health", key, data={"key": key, **h})
    store.heartbeat(run_id)

    funnel = {"fetched": len(all_jobs), "role": 0, "geography": 0, "score": 0,
              "deduped": 0, "kept": 0}
    kept: list[dict] = []
    for job in all_jobs:
        v = score_job(job, mode=geography, strictness=strictness)
        if not v.keep:
            funnel[v.stage] = funnel.get(v.stage, 0) + 1
            continue
        if store.already_handled(job.dedupe_key, job.content_hash, job.apply_url):
            funnel["deduped"] += 1
            continue
        funnel["kept"] += 1
        kept.append({"job": job, "score": v.score, "signals": v.signals})
    _emit(run_id, "funnel.update", "funnel", data=funnel)

    # Order by sendability first, then score: boards that have blocked us before
    # (CAPTCHA / no usable form) still get prepared, but after the ones that can
    # actually auto-send, so a capped run spends its effort where it pays off.
    blocked = store.blocked_companies()
    kept.sort(key=lambda k: (k["job"].company in blocked, -k["score"]))
    selected = kept[:cap]
    deferred = sum(1 for k in selected if k["job"].company in blocked)
    _emit(run_id, "phase", f"{len(all_jobs)} fetched · {funnel['kept']} relevant "
                           f"· preparing top {len(selected)}"
                           + (f" ({deferred} known-blocked last)" if deferred else ""))

    added = _add_items(run_id, selected)
    if added:
        ctx = await session.ats_context(headless=True)   # reused across runs
        await _prepare_loop(run_id, ctx, adapters, cancel, profile, cv_path,
                            concurrency=int(options.get("concurrency",
                                                        config.PREPARE_CONCURRENCY)))
    return max(0, cap - added)


def _add_items(run_id, selected) -> int:
    n = 0
    for k in selected:
        job = k["job"]
        iid = store.add_item(run_id, {
            "channel": job.channel, "company": job.company, "title": job.title,
            "location": job.location, "url": job.url, "apply_url": job.apply_url,
            "dedupe_key": job.dedupe_key, "content_hash": job.content_hash,
            "score": k["score"], "score_json": {"signals": k["signals"]},
            "state": "queued"})
        if iid:
            n += 1
            _emit(run_id, "item.new", job.title, item_id=iid,
                  data={"company": job.company, "title": job.title,
                        "channel": job.channel, "score": k["score"],
                        "state": "queued"})
    return n


async def _prepare_loop(run_id, ctx, adapters, cancel, profile, cv_path,
                        concurrency: int = 1):
    """Drain the queued items.

    PREPARE only reads and fills forms — it never submits — so it is safe to run
    several in parallel, each on its own page in the shared context. That is the
    difference between ~8s/item serially and a batch of 100 finishing in minutes.
    Sends stay strictly sequential elsewhere (rate limiting / account safety).
    Item claiming is race-free: transition_item() only succeeds for one worker.
    """
    import asyncio

    async def _one_worker():
        while True:
            cancel.check()
            store.heartbeat(run_id)
            it = store.next_queued(run_id)
            if not it:
                return
            if not store.transition_item(it["id"], ["queued"], "preparing"):
                continue                      # another worker claimed it
            _emit(run_id, "item.state", "preparing", item_id=it["id"],
                  data={"state": "preparing"})
            adapter = adapters.get(it["channel"])
            job = _job_from_item(it)
            try:
                res = await adapter.prepare(ctx, job, profile, cv_path, cancel)
            except Cancelled:
                store.transition_item(it["id"], ["preparing"], "queued")
                raise
            except Exception as e:
                res = None
                _emit(run_id, "item.error", str(e)[:160], item_id=it["id"],
                      level="error")
            _apply_prepare_result(run_id, it, res, cv_path, profile)
            await cancel.sleep(config.PREPARE_DELAY_S)

    n = max(1, int(concurrency))
    if n == 1:
        await _one_worker()
        return
    results = await asyncio.gather(*[_one_worker() for _ in range(n)],
                                   return_exceptions=True)
    for r in results:                          # propagate a real cancel
        if isinstance(r, Cancelled):
            raise r
        if isinstance(r, BaseException) and not isinstance(r, Exception):
            raise r


async def _prepare_linkedin(run_id, options, cancel, cap, profile, cv_path):
    from ..channels.linkedin import LinkedInChannel
    geography = options.get("geography", "israel_remote")
    strictness = options.get("strictness", "balanced")
    headless = not options.get("show_browser", False)
    li = LinkedInChannel()

    _emit(run_id, "phase", "Opening LinkedIn…")
    # Reused persistent context — headless by default (no window per run).
    ctx = await session.linkedin_context(headless=headless)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    if not await li.logged_in(page):
        _emit(run_id, "run.error",
              "LinkedIn not logged in — log in once, then re-run.", level="warn")
        return
    _emit(run_id, "phase", "Searching LinkedIn Easy Apply roles…")
    jobs = await li.discover(page, geography)
    kept = []
    for job in jobs:
        v = score_job(job, mode=geography, strictness=strictness)
        if not v.keep:
            continue
        if store.already_handled(job.dedupe_key, job.content_hash, job.apply_url):
            continue
        kept.append({"job": job, "score": v.score, "signals": v.signals})
    kept.sort(key=lambda k: k["score"], reverse=True)
    _add_items(run_id, kept[:cap])
    await _prepare_loop(run_id, ctx, {"linkedin": li}, cancel, profile, cv_path)


async def run_takeover(item_id: int, cancel) -> None:
    """Fill this application again in a VISIBLE window and leave it open.

    The page is deliberately NOT closed and nothing is submitted: the human
    finishes the last step (CAPTCHA / a question we won't invent an answer to)
    and clicks submit themselves, then marks it sent in the UI.
    """
    it = store.get_item(item_id)
    if not it:
        return
    profile = store.get_profile() or {}
    cv_path = profile.get("cv_path") or ""
    run_id = it["run_id"]

    if it["channel"] == "linkedin":
        ctx = await session.linkedin_context(headless=False)
        from ..channels.linkedin import LinkedInChannel
        adapter = LinkedInChannel()
    else:
        ctx = await session.ats_context(headless=False)
        adapter = build_adapters({"channels": [it["channel"]]}).get(it["channel"])
    if adapter is None:
        return

    _emit(run_id, "item.state", it["state"], item_id=item_id,
          data={"state": it["state"], "reason": "opening pre-filled window…"})
    # NOTE: we deliberately do NOT call adapter.prepare() here — it closes its
    # page in a finally block, which would make the window vanish. Fill with the
    # shared helpers instead and leave the page open for the human.
    page = await ctx.new_page()
    try:
        await page.goto(it["apply_url"], wait_until="domcontentloaded",
                        timeout=45000)
        await page.wait_for_timeout(2000)
        if it["channel"] == "linkedin":
            await adapter._open_modal(page)      # LinkedIn pre-fills from profile
        else:
            from ..channels import atsform
            from ..engine import answerbank as ab
            root = page.main_frame
            if it["channel"] == "greenhouse":
                from ..channels.greenhouse import _form_root
                root = await _form_root(page)
            filled, answers = [], {}
            await atsform.fill_all_text(root, ab.profile_values(profile),
                                        filled, answers)
            await atsform.attach_cv(root, cv_path)
    except Exception as e:
        _emit(run_id, "item.error", f"take-over: {e}"[:160], item_id=item_id,
              level="warn")
    _emit(run_id, "item.state", it["state"], item_id=item_id,
          data={"state": it["state"],
                "reason": "window open — finish it, then press 'I sent it'"})


def _apply_prepare_result(run_id, it, res, cv_path, profile):
    if res is None:
        store.transition_item(it["id"], ["preparing"], "failed",
                              reason="prepare crashed")
        _emit(run_id, "item.state", "failed", item_id=it["id"],
              data={"state": "failed"})
        return
    result_json = {
        "filled": [f.__dict__ for f in res.filled],
        "questions": [q.__dict__ for q in res.questions],
        "cv_attached": res.cv_attached,
    }
    # Durable SendHandle snapshot (incl. CV hash for the changed-CV guard).
    handle = {
        "dedupe_key": it["dedupe_key"], "channel": it["channel"],
        "apply_url": it["apply_url"], "company": it.get("company"),
        "title": it.get("title"), "answers": res.answers,
        "cv_path": cv_path, "cv_sha256": (profile or {}).get("cv_sha256", ""),
    }
    result_json["handle"] = handle
    state = {READY: "ready", NEEDS_INPUT: "needs_input",
             FAILED: "failed", SKIPPED: "skipped"}.get(res.state, "failed")
    fields = {"reason": res.reason, "result_json": json.dumps(result_json)}
    if res.screenshot:
        fields["screenshot_prepare"] = res.screenshot
    fields["attempts"] = (it.get("attempts") or 0) + 1
    store.transition_item(it["id"], ["preparing"], state, **fields)
    _emit(run_id, "item.state", state, item_id=it["id"],
          data={"state": state, "reason": res.reason,
                "screenshot": res.screenshot})


async def run_send(run_id: int, cancel) -> None:
    """SEND phase: drain every item the human confirmed into 'sending', re-fill
    and perform the one irreversible submit, then verify. Strictly sequential +
    rate-limited (ban safety); late confirms are picked up in the same drain."""
    profile = store.get_profile()
    from ..channels.registry import IMPLEMENTED
    adapters = build_adapters({"channels": list(IMPLEMENTED)})
    store.update_run(run_id, status="sending", phase="send")
    import random
    from ..channels.linkedin import LinkedInChannel
    show = bool(store.get_run(run_id).get("options_json") and
                json.loads(store.get_run(run_id)["options_json"] or "{}")
                .get("show_browser"))
    while True:
        try:
            cancel.check()
        except Cancelled:
            break
        store.heartbeat(run_id)
        it = store.next_in_state(run_id, "sending")
        if not it:
            break
        iid = it["id"]
        rj = json.loads(it.get("result_json") or "{}")
        h = rj.get("handle") or {}
        handle = SendHandle(
            dedupe_key=h.get("dedupe_key", it["dedupe_key"]),
            channel=it["channel"], apply_url=h.get("apply_url", it["apply_url"]),
            company=h.get("company", ""), title=h.get("title", ""),
            answers=h.get("answers", {}), cv_path=h.get("cv_path", ""),
            cv_sha256=h.get("cv_sha256", ""))

        # CV-changed-between-prepare-and-send guard.
        bad = _cv_guard(handle, profile)
        if bad:
            store.transition_item(iid, ["sending"], "needs_input", reason=bad)
            _emit(run_id, "item.state", "needs_input", item_id=iid,
                  data={"state": "needs_input", "reason": bad})
            continue

        # Route to the right reused context: LinkedIn needs the logged-in
        # profile; ATS uses the shared ephemeral one. Both are kept alive by
        # the session, so sending opens pages — not browsers.
        if it["channel"] == "linkedin":
            ctx = await session.linkedin_context(headless=not show)
            adapter = LinkedInChannel()
        else:
            ctx = await session.ats_context(headless=not show)
            adapter = adapters.get(it["channel"])
        try:
            res = await adapter.send(ctx, handle, cancel)
        except Cancelled:
            _emit(run_id, "item.state", "sending", item_id=iid,
                  data={"state": "sending",
                        "reason": "cancel — verify this one manually"})
            break
        except Exception as e:
            res = None
            _emit(run_id, "item.error", str(e)[:160], item_id=iid, level="error")

        _apply_send_result(run_id, it, res)
        delay = config.SEND_DELAY_S + random.uniform(0, config.SEND_JITTER_S)
        try:
            await cancel.sleep(delay)
        except Cancelled:
            break

    counts = store.item_counts(run_id)
    status = "awaiting_confirm" if counts.get("ready") or counts.get("needs_input") \
        else "done"
    store.update_run(run_id, status=status,
                     finished_at=(time.time() if status == "done" else None),
                     message=f"Sent {counts.get('sent', 0)} · "
                             f"{counts.get('sent_unverified', 0)} unverified")
    _emit(run_id, "run.state", status, data={"status": status, "counts": counts})


def _cv_guard(handle: SendHandle, profile: dict) -> str:
    import hashlib
    from pathlib import Path
    p = Path(handle.cv_path or (profile or {}).get("cv_path") or "")
    if not p.exists():
        return "CV file missing — re-upload before sending"
    if handle.cv_sha256:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != handle.cv_sha256:
            return "CV changed since review — re-review before sending"
    return ""


def _apply_send_result(run_id, it, res):
    if res is None:
        store.transition_item(it["id"], ["sending"], "failed",
                              reason="send crashed")
        _emit(run_id, "item.state", "failed", item_id=it["id"],
              data={"state": "failed"})
        return
    if res.state == SENT:
        ev = res.evidence.to_json() if res.evidence else ""
        moved = store.transition_item(
            it["id"], ["sending"], "sent", reason="sent",
            confirmation_evidence=ev,
            screenshot_after=res.screenshot or "")
        if moved:
            item = store.get_item(it["id"])
            store.record_application(item, ev)      # terminal, idempotent
        _emit(run_id, "item.state", "sent", item_id=it["id"],
              data={"state": "sent", "evidence": ev})
    elif res.state == SENT_UNVERIFIED:
        store.transition_item(it["id"], ["sending"], "sent_unverified",
                              reason=res.reason,
                              screenshot_after=res.screenshot or "")
        _emit(run_id, "item.state", "sent_unverified", item_id=it["id"],
              data={"state": "sent_unverified", "reason": res.reason})
    else:
        target = "needs_input" if res.state == "needs_input" else "failed"
        store.transition_item(it["id"], ["sending"], target, reason=res.reason)
        _emit(run_id, "item.state", target, item_id=it["id"],
              data={"state": target, "reason": res.reason})
