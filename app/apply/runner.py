"""Run orchestration: fetch -> filter -> dedupe -> apply.

Runs in a background worker thread (started from main.py) using Playwright's
sync API. Progress and results are written to the `run` table so the web UI can
poll /status.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

import httpx
import yaml

from .. import db, filtering
from ..sources import FETCHERS
from . import browser, linkedin
from .forms import generic

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BOARDS_PATH = DATA_DIR / "boards.yaml"
SHOTS_DIR = DATA_DIR / "screenshots"

DEFAULT_OPTIONS = {
    "submit": False,        # dry run by default — fill only, never submit
    "cap": 20,              # max applications attempted this run (total)
    "delay": 5.0,           # seconds between applications (rate limit)
    "use_ats": True,        # Greenhouse / Lever / Ashby / Comeet
    "use_linkedin": False,  # LinkedIn Easy Apply
    "geography": "israel_remote",
}


def load_boards() -> dict:
    if not BOARDS_PATH.exists():
        return {}
    with open(BOARDS_PATH) as f:
        data = yaml.safe_load(f) or {}
    # Normalize: {source: [tokens]}; ignore unknown sources.
    return {k: (v or []) for k, v in data.items() if k in FETCHERS}


def gather_ats_jobs(boards: dict, mode: str, log) -> list[dict]:
    out: list[dict] = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for source, tokens in boards.items():
            fetch = FETCHERS[source]
            for token in tokens:
                jobs = fetch(token, client=client)
                for j in jobs:
                    db.upsert_job(j)
                kept = [j for j in jobs if filtering.relevance(j, mode)[0]]
                if kept:
                    log(f"{source}:{token} -> {len(kept)} relevant / {len(jobs)} total")
                out.extend(kept)
    return out


def _screenshot(page, run_id: int, idx: int) -> str:
    try:
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOTS_DIR / f"run{run_id}_{idx}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path.relative_to(DATA_DIR.parent))
    except Exception:
        return ""


def execute_run(run_id: int, options: dict) -> None:
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    stats = {
        "options": opts,
        "applied": 0, "needs_review": 0, "failed": 0, "filled": 0,
        "scanned": 0, "items": [], "log": [],
    }

    def log(msg: str):
        stats["log"].append(msg)
        db.update_run(run_id, "running", message=msg, stats=stats)

    profile = db.get_profile()
    if not profile or not profile.get("email"):
        db.update_run(run_id, "error",
                      message="Set up your profile (name, email, CV) first.",
                      stats=stats, finished=True)
        return
    if not profile.get("cv_path") or not Path(profile["cv_path"]).exists():
        db.update_run(run_id, "error",
                      message="Upload your CV (PDF) on the profile page first.",
                      stats=stats, finished=True)
        return

    cv_path = profile["cv_path"]
    mode = opts["geography"]
    remaining = int(opts["cap"])

    try:
        # ---------------- gather ATS candidates --------------------------
        ats_candidates: list[dict] = []
        if opts["use_ats"]:
            log("Fetching jobs from ATS feeds (Greenhouse/Lever/Ashby/Comeet)…")
            ats_jobs = gather_ats_jobs(load_boards(), mode, log)
            seen = set()
            for j in ats_jobs:
                key = (j["source"], j["company"], j["external_id"])
                if key in seen or db.already_handled(*key):
                    continue
                seen.add(key)
                ats_candidates.append(j)
            log(f"{len(ats_candidates)} new relevant ATS roles after dedupe.")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # ---------------- apply to ATS forms -------------------------
            if ats_candidates and remaining > 0:
                br, ctx = browser.launch_browser(p, headless=False)
                try:
                    for job in ats_candidates:
                        if remaining <= 0:
                            break
                        stats["scanned"] += 1
                        page = ctx.new_page()
                        try:
                            page.goto(job["apply_url"], timeout=40000)
                            res = generic.fill_form(page, profile, cv_path,
                                                    submit=opts["submit"])
                        except Exception as e:
                            res = {"status": "failed", "reason": str(e)[:120]}
                        shot = _screenshot(page, run_id, stats["scanned"])
                        _record(job, res, shot, stats, opts)
                        page.close()
                        remaining -= 1
                        db.update_run(run_id, "running",
                                      message=f"Applied/scanned {stats['scanned']}…",
                                      stats=stats)
                        time.sleep(opts["delay"])
                finally:
                    ctx.close()
                    br.close()

            # ---------------- LinkedIn Easy Apply ------------------------
            if opts["use_linkedin"] and remaining > 0:
                log("Opening LinkedIn…")
                ctx = browser.launch_persistent(p, headless=False)
                try:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    if not linkedin.is_logged_in(page):
                        log("Please log in to LinkedIn in the opened window…")
                        try:
                            page.goto("https://www.linkedin.com/login")
                        except Exception:
                            pass
                        # Wait up to 3 minutes for a manual login.
                        for _ in range(36):
                            time.sleep(5)
                            if linkedin.is_logged_in(page):
                                break
                    if not linkedin.is_logged_in(page):
                        log("LinkedIn login not detected — skipping LinkedIn.")
                    else:
                        log("Searching LinkedIn Easy Apply junior roles…")
                        lk = linkedin.search_easy_apply_jobs(page, location="Israel")
                        lk = [j for j in lk
                              if filtering.is_junior(j["title"]) or
                              filtering.is_software_role(j["title"])]
                        fresh = [j for j in lk
                                 if not db.already_handled(j["source"], j["company"],
                                                           j["external_id"])]
                        log(f"{len(fresh)} LinkedIn Easy Apply candidates.")
                        for job in fresh:
                            if remaining <= 0:
                                break
                            stats["scanned"] += 1
                            try:
                                res = linkedin.apply_easy_apply(
                                    page, job, profile, cv_path, submit=opts["submit"])
                            except Exception as e:
                                res = {"status": "failed", "reason": str(e)[:120]}
                            shot = _screenshot(page, run_id, stats["scanned"])
                            _record(job, res, shot, stats, opts)
                            remaining -= 1
                            db.update_run(run_id, "running",
                                          message=f"LinkedIn {stats['scanned']}…",
                                          stats=stats)
                            time.sleep(opts["delay"])
                finally:
                    ctx.close()

        summary = (f"Done. submitted={stats['applied']} "
                   f"needs_review={stats['needs_review']} "
                   f"failed={stats['failed']} filled={stats['filled']}")
        db.update_run(run_id, "done", message=summary, stats=stats, finished=True)

    except Exception as e:
        tb = traceback.format_exc()
        hint = ""
        if "Executable doesn't exist" in tb or "playwright install" in tb:
            hint = " — run: playwright install chromium"
        db.update_run(run_id, "error",
                      message=f"Run failed: {e}{hint}"[:300],
                      stats=stats, finished=True)


def _record(job: dict, res: dict, shot: str, stats: dict, opts: dict) -> None:
    status = res.get("status", "failed")
    reason = res.get("reason", "")
    # Map filler statuses to stored application statuses.
    if status == "submitted":
        stored, bucket = "applied", "applied"
    elif status == "filled":
        stored, bucket = None, "filled"   # dry run: don't persist (re-runnable)
    elif status == "needs_review":
        stored, bucket = "needs_review", "needs_review"
    else:
        stored, bucket = "failed", "failed"

    stats[bucket] = stats.get(bucket, 0) + 1
    stats["items"].append({
        "source": job["source"], "company": job["company"],
        "title": job.get("title", ""), "url": job.get("url", ""),
        "apply_url": job.get("apply_url", ""),
        "status": status, "reason": reason, "screenshot": shot,
    })
    # Persist only terminal real outcomes (so dry runs stay repeatable).
    if stored and not (opts["submit"] is False and status == "filled"):
        db.record_application(job, stored, reason=reason, screenshot_path=shot)
