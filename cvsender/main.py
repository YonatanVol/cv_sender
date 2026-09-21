"""FastAPI app for CV Sender v2 — JSON + SSE API and the served UI.

The confirm endpoints trigger real, irreversible outward actions, so the server
binds to loopback only (config.HOST) and mutating routes check the Origin.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import auth, cloud, config, cv as cvmod, health, scheduler
from .core.run_manager import manager
from .db import store
from .db.migrations import migrate

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"

app = FastAPI(title="CV Sender v2")


def _cloud_bg(fn, *args):
    """Run a cloud sync off the request thread; it must never block the UI
    or fail a request (the cloud is a mirror, the local DB is the truth)."""
    def _run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_run, daemon=True, name="cloud-sync").start()


@app.on_event("startup")
def _startup():
    migrate()
    _cloud_bg(cloud.sync_on_start)   # bootstrap from / mirror to the cloud
    scheduler.start()                # keeps the queue stocked; never sends
    # Refuse to be reachable off-machine without a passphrase: these endpoints
    # fire real, irreversible applications.
    if config.HOST not in ("127.0.0.1", "localhost", "::1") \
            and not auth.is_configured():
        raise RuntimeError(
            f"Refusing to bind {config.HOST} without authentication. "
            "Set a passphrase first (open the app on localhost -> Settings, "
            "or run: python -m cvsender.setpass).")
    # Housekeeping, not a precondition. A run that is mid-write holds the
    # database long enough that this raised "database is locked" and killed
    # startup outright; the service only came back because launchd retried.
    # Both sweeps also run from /api/assist, so skipping one costs nothing.
    try:
        swept = store.sweep_stale_runs(config.STALE_RUN_S)
        if swept:
            print(f"[startup] recovered stale runs: {swept}")
        stuck = store.sweep_stuck_items(config.STUCK_ITEM_S)
        if stuck:
            print(f"[startup] rescued {stuck} item(s) stuck in 'sending'")
    except sqlite3.OperationalError as e:
        print(f"[startup] skipped the run sweep, database busy: {e}")


# Only form screenshots are served from the data directory. The folder also
# holds the owner secret (cloud.json), the database and the LinkedIn cookies,
# so it must never be mounted as a whole.
_SHOT_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg"}


@app.get("/data2/shots/{name}")
def screenshot(name: str):
    root = config.SCREENSHOT_DIR.resolve()
    try:
        path = (root / name).resolve()
    except (OSError, ValueError):
        raise HTTPException(404, "not found")
    if path.parent != root or path.suffix.lower() not in _SHOT_TYPES \
            or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=_SHOT_TYPES[path.suffix.lower()],
                        headers={"Cache-Control": "private, max-age=86400"})


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


# --------------------------- consent / origin ------------------------------

PUBLIC_PATHS = {"/login", "/api/login", "/static/manifest.webmanifest",
                "/static/icon.svg", "/api/auth/status", "/healthz",
                # the browser asks for this before you are signed in; answering
                # it with a redirect to /login put a 303 on every page load
                "/favicon.ico"}


def _is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """Gate everything once a passphrase is set.

    Loopback stays open when no passphrase is configured, so local use is
    unchanged; as soon as one exists (i.e. the user intends remote access),
    every request must carry a valid session.
    """
    path = request.url.path
    if not auth.is_configured() or path in PUBLIC_PATHS \
            or path.startswith("/static/"):
        return await call_next(request)
    if auth.valid_session(request.cookies.get(auth.COOKIE)):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/favicon.ico")
def favicon():
    return FileResponse(str(WEB / "icon.svg"), media_type="image/svg+xml")


@app.get("/login")
def login_page():
    return FileResponse(str(WEB / "login.html"))


@app.get("/api/auth/status")
def auth_status(request: Request):
    return JSONResponse({
        "configured": auth.is_configured(),
        "authenticated": auth.valid_session(request.cookies.get(auth.COOKIE)),
        "loopback": _is_loopback(request),
    })


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    client = (request.client.host if request.client else "?") or "?"
    wait = auth.locked_out(client)
    if wait:
        raise HTTPException(429, f"too many attempts — try again in {int(wait)}s")
    if not auth.verify_passphrase(body.get("passphrase") or ""):
        auth.note_failure(client)
        raise HTTPException(401, "wrong passphrase")
    auth.clear_failures(client)
    token = auth.create_session()
    resp = JSONResponse({"ok": True})
    # Secure only over real HTTPS: a Secure cookie is dropped on plain-HTTP LAN,
    # which would silently make login impossible.
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https",
                    max_age=auth.SESSION_TTL_S, path="/")
    return resp


@app.post("/api/auth/logout-all")
async def logout_all(request: Request):
    """Sign out every device. Use after losing a phone, or to force a re-login."""
    _check_origin(request)
    n = auth.destroy_all_sessions()
    resp = JSONResponse({"ok": True, "signed_out": n})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/logout")
async def logout(request: Request):
    auth.destroy_session(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/auth/passphrase")
async def set_passphrase(request: Request):
    """Set or change the passphrase. Only allowed from loopback, or when already
    authenticated — never anonymously from the network."""
    _check_origin(request)
    if auth.is_configured():
        if not auth.valid_session(request.cookies.get(auth.COOKIE)):
            raise HTTPException(401, "log in first")
    elif not _is_loopback(request):
        raise HTTPException(403, "set the passphrase from the local machine")
    body = await request.json()
    try:
        auth.set_passphrase(body.get("passphrase") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"ok": True})


def local_origins() -> set[str]:
    """Every origin this server legitimately answers on.

    config.HOST is the BIND address: with --remote it is 0.0.0.0, which no
    browser ever sends as an Origin, so the old check rejected every POST from
    the phone (403 on 'I sent it'). The allow-list is built from the machine's
    real addresses instead, plus an optional public_origin setting for a
    Tailscale or tunnel hostname. It is an explicit list, never "Origin equals
    Host", which a DNS-rebinding page can forge.
    """
    hosts = {"localhost", "127.0.0.1", "::1"}
    if config.HOST not in ("0.0.0.0", "::"):
        hosts.add(config.HOST)
    try:
        hostname = socket.gethostname()
        hosts.add(hostname)
        hosts.add(f"{hostname}.local")
        for info in socket.getaddrinfo(hostname, None):
            hosts.add(info[4][0])
    except OSError:
        pass
    origins = set()
    for h in hosts:
        h = f"[{h}]" if ":" in h and not h.startswith("[") else h
        origins.add(f"http://{h}:{config.PORT}")
        origins.add(f"https://{h}:{config.PORT}")
        origins.add(f"https://{h}")
    extra = store.get_setting("public_origin")
    if extra:
        origins.add(extra.rstrip("/"))
    return origins


def phone_access() -> dict:
    """How to reach this app from the phone, as a name rather than an address.

    An IP changes with the network and is nobody's idea of a link. The Mac's
    Bonjour name (…​.local) is stable and resolves on the same Wi-Fi from an
    iPhone without installing anything. Off Wi-Fi needs Tailscale, which only
    Yonatan can install, so we report honestly whether it is there.
    """
    name = socket.gethostname().split(".")[0]
    tailnet = store.get_setting("public_origin") or ""
    ts = shutil.which("tailscale") or (
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        if os.path.exists("/Applications/Tailscale.app") else "")
    return {
        "lan_url": f"http://{name}.local:{config.PORT}",
        "lan_works": "on the same Wi-Fi as this Mac",
        "anywhere_url": tailnet,
        "tailscale_installed": bool(ts),
    }


@app.get("/api/where")
def api_where():
    return JSONResponse(phone_access())


def _check_origin(request: Request) -> None:
    """Reject cross-origin mutations of the irreversible endpoints."""
    origin = request.headers.get("origin")
    if origin is None:
        return  # same-origin fetch / curl without Origin
    if origin.rstrip("/") not in local_origins():
        raise HTTPException(403, "cross-origin request rejected")


# ------------------------------- pages -------------------------------------

@app.get("/")
def index():
    return FileResponse(str(WEB / "index.html"))


@app.get("/assist")
def assist_page():
    """Burst mode: clear blocked applications fast (also the PWA start_url)."""
    return FileResponse(str(WEB / "assist.html"))


# ------------------------------ profile ------------------------------------

@app.get("/api/profile")
def get_profile():
    return JSONResponse(store.get_profile() or {})


@app.put("/api/profile")
async def put_profile(request: Request):
    _check_origin(request)
    body = await request.json()
    data = {
        "full_name": (body.get("full_name") or "").strip(),
        "email": (body.get("email") or "").strip(),
        "phone": (body.get("phone") or "").strip(),
        "location": (body.get("location") or "Israel").strip(),
        "region": (body.get("region") or "Israel").strip(),
        "linkedin": (body.get("linkedin") or "").strip(),
        "github": (body.get("github") or "").strip(),
        "portfolio": (body.get("portfolio") or "").strip(),
        # Real booleans — no HTML-checkbox 'on'-default bug.
        "needs_sponsorship": 1 if body.get("needs_sponsorship") else 0,
        "work_authorized_il": 1 if body.get("work_authorized_il", True) else 0,
    }
    store.save_profile(data)
    _cloud_bg(cloud.push_profile)
    return JSONResponse(store.get_profile())


@app.post("/api/cv")
async def upload_cv(request: Request, cv: UploadFile = File(...)):
    _check_origin(request)
    raw = await cv.read()
    try:
        meta = cvmod.save_cv(raw, cv.filename or "cv.pdf")
    except cvmod.CvError as e:
        raise HTTPException(400, str(e))
    store.save_profile(meta)
    def _mirror_cv(path=meta["cv_path"]):
        cloud.upload_cv(path)
        cloud.push_profile()
    _cloud_bg(_mirror_cv)
    return JSONResponse({"ok": True, **meta})


# -------------------------------- runs -------------------------------------

@app.post("/api/runs")
async def create_run(request: Request):
    _check_origin(request)
    body = await request.json()
    options = {
        "channels": body.get("channels") or ["greenhouse"],
        "mode": "live" if body.get("mode") == "live" else "dry",
        "cap": max(1, min(int(body.get("cap", 20)), config.MAX_CAP)),
        "concurrency": max(1, min(int(body.get("concurrency",
                                               config.PREPARE_CONCURRENCY)), 8)),
        "geography": body.get("geography", "israel_remote"),
        "strictness": body.get("strictness", "balanced"),
    }
    prof = store.get_profile()
    if not prof or not prof.get("email"):
        raise HTTPException(400, "Set up your profile (name + email) first.")
    if not prof.get("cv_path") or not Path(prof["cv_path"]).exists():
        raise HTTPException(400, "Upload your CV (PDF) first.")

    run_id = store.create_run_atomic(options, options["mode"])
    if run_id is None:
        active = store.get_active_run()
        raise HTTPException(409, f"A run is already active (#{active['id'] if active else '?'})")
    manager.start_prepare(run_id, options)
    return JSONResponse({"run_id": run_id}, status_code=201)


@app.get("/api/runs/active")
def active_run():
    """The working run, or the newest one parked for your confirm."""
    return JSONResponse(store.get_active_run() or store.parked_run() or {})


@app.get("/api/runs")
def runs():
    return JSONResponse(store.list_runs())


@app.get("/api/runs/{run_id}")
def run_snapshot(run_id: int):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    return JSONResponse({
        "run": run,
        "items": store.list_items(run_id),
        "counts": store.item_counts(run_id),
    })


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request):
    _check_origin(request)
    manager.request_cancel(run_id)
    # If no worker is active (e.g. the run is parked in awaiting_confirm), the
    # worker can't finalize it — close it here so a new run can start.
    run = store.get_run(run_id)
    if run and run["status"] == "awaiting_confirm" and not manager.busy():
        store.update_run(run_id, status="cancelled", finished_at=time.time(),
                         message="Closed by user")
        store.add_event(run_id, "run.state", "cancelled",
                        data={"status": "cancelled"})
    return JSONResponse({"ok": True}, status_code=202)


@app.post("/api/runs/{run_id}/items/{item_id}/confirm")
async def confirm_item(run_id: int, item_id: int, request: Request):
    _check_origin(request)
    run = store.get_run(run_id)
    if not run or run.get("mode") != "live":
        raise HTTPException(400, "confirm is only allowed on a LIVE run")
    if not store.transition_item(item_id, ["ready"], "sending"):
        raise HTTPException(409, "item not in a ready state (already sent/queued?)")
    store.add_event(run_id, "item.state", "sending", item_id=item_id,
                    data={"state": "sending"})
    _ensure_send_worker(run_id)
    return JSONResponse({"ok": True}, status_code=202)


def _ensure_send_worker(run_id: int) -> None:
    """Start the send worker if there are items to send and none is running.
    Retries briefly so a confirm that races the prepare-thread teardown still
    launches the sender (fixes items getting stuck in 'sending')."""
    if not store.list_items(run_id, ["sending"]):
        return
    for _ in range(20):                      # ~2s of retries past teardown
        if manager.start_send(run_id):
            return
        if store.get_active_run() and store.get_active_run()["status"] == "sending":
            return                           # a sender is already draining
        time.sleep(0.1)


@app.post("/api/runs/{run_id}/confirm-all")
async def confirm_all(run_id: int, request: Request):
    _check_origin(request)
    run = store.get_run(run_id)
    if not run or run.get("mode") != "live":
        raise HTTPException(400, "confirm is only allowed on a LIVE run")
    ready = store.list_items(run_id, ["ready"])
    n = 0
    for it in ready:
        if store.transition_item(it["id"], ["ready"], "sending"):
            store.add_event(run_id, "item.state", "sending", item_id=it["id"],
                            data={"state": "sending"})
            n += 1
    if n:
        _ensure_send_worker(run_id)
    return JSONResponse({"confirmed": n}, status_code=202)


# ------------------------- assist queue (throughput) ------------------------
# The bot fills everything and parks blocked applications here; the human
# clears them in seconds. This is what converts CAPTCHA / screening-question
# items into real sends. No AI involved — pure state + links.

@app.get("/api/assist")
def assist_queue(limit: int = 200):
    """Everything a human could finish right now, newest/best first."""
    # The dashboard polls this, so it doubles as the watchdog tick: rescue any
    # item wedged in 'sending' so it becomes finishable instead of invisible.
    if not manager.busy():
        store.sweep_stuck_items(config.STUCK_ITEM_S)
    items = store.assist_queue(limit)
    out = []
    for it in items:
        rj = json.loads(it.get("result_json") or "{}")
        sj = json.loads(it.get("score_json") or "{}")
        out.append({
            "id": it["id"], "run_id": it["run_id"], "channel": it["channel"],
            "company": it["company"], "title": it["title"],
            "apply_url": it["apply_url"], "url": it["url"],
            "state": it["state"], "reason": it["reason"], "score": it["score"],
            # the card shows how good the fit is, not only the number
            "band": sj.get("band", ""),
            "screenshot": it["screenshot_prepare"],
            "cv_attached": rj.get("cv_attached", False),
            "filled": [f.get("label") for f in rj.get("filled", [])],
            "questions": rj.get("questions", []),
        })
    return JSONResponse({
        "items": out,
        "sent_today": store.sent_today(),
        "counts": {"blocked": len(out)},
    })


@app.post("/api/items/{item_id}/mark-sent")
async def mark_sent(item_id: int, request: Request):
    """The human finished this application themselves (phone or browser).
    Records a user-confirmed send so it counts, dedupes, and enters the Tracker."""
    _check_origin(request)
    it = store.get_item(item_id)
    if not it:
        raise HTTPException(404, "no such item")
    if it["state"] == "sent":
        return JSONResponse({"ok": True, "already": True})
    evidence = json.dumps({"method": "user", "detail": "confirmed by user",
                           "at": time.time()})
    store.transition_item(item_id, ["needs_input", "failed", "ready",
                                    "sending", "sent_unverified"], "sent",
                          reason="sent (confirmed by you)",
                          confirmation_evidence=evidence)
    item = store.get_item(item_id)
    store.record_application(item, evidence)
    store.bump_daily(item["channel"])
    store.add_event(it["run_id"], "item.state", "sent", item_id=item_id,
                    data={"state": "sent", "evidence": "user"})
    return JSONResponse({"ok": True, "sent_today": store.sent_today()})


@app.post("/api/items/{item_id}/unavailable")
async def mark_unavailable(item_id: int, request: Request):
    """The posting is gone / closed when you click through.

    Distinct from 'skip' (which means "not now" and comes back) and from 'sent'
    (it was never sent, so it must not touch the sent count). Recorded in
    `dismissed`, which the dedupe path consults, so it stops being re-staged on
    every future run.
    """
    _check_origin(request)
    it = store.get_item(item_id)
    if not it:
        raise HTTPException(404, "no such item")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    kind = body.get("kind") or "unavailable"
    store.dismiss(it, kind=kind, note=body.get("note") or "")
    store.transition_item(item_id, ["needs_input", "failed", "ready",
                                    "sending", "sent_unverified"], "skipped",
                          reason="no longer available")
    store.add_event(it["run_id"], "item.state", "skipped", item_id=item_id,
                    data={"state": "skipped", "reason": kind})
    return JSONResponse({"ok": True, "dismissed": store.dismissed_count()})


@app.get("/settings")
def settings_page():
    return FileResponse(str(WEB / "settings.html"))


RUN_DEFAULTS = {"geography": "israel_remote", "strictness": "balanced",
                "target": "100", "channels": "greenhouse,lever,ashby,comeet,linkedin"}


@app.get("/api/settings")
def get_settings():
    """Run defaults, editable from any device (they live in the DB, not a file)."""
    out = {k: (store.get_setting(f"run.{k}") or v) for k, v in RUN_DEFAULTS.items()}
    out["channels"] = [c for c in out["channels"].split(",") if c]
    return JSONResponse(out)


@app.put("/api/settings")
async def put_settings(request: Request):
    _check_origin(request)
    body = await request.json()
    for k in RUN_DEFAULTS:
        if k not in body:
            continue
        val = body[k]
        if k == "channels":
            val = ",".join(val if isinstance(val, list) else [])
        store.set_setting(f"run.{k}", str(val))
    pairs = {k: (",".join(body[k]) if k == "channels" and isinstance(body[k], list)
                 else str(body[k])) for k in RUN_DEFAULTS if k in body}
    _cloud_bg(cloud.push_settings, pairs)
    return await get_settings_async()


async def get_settings_async():
    return get_settings()


@app.get("/api/cloud/status")
def cloud_status():
    return JSONResponse(cloud.status())


@app.post("/api/cloud/restore")
async def cloud_restore(request: Request):
    """Explicit 'Restore from cloud': the cloud copy wins. Use on a new
    device, or after a local wipe."""
    _check_origin(request)
    return JSONResponse(cloud.restore(overwrite=True))


@app.post("/api/cloud/push")
async def cloud_push(request: Request):
    """Explicit 'Back up now': push everything local to the cloud."""
    _check_origin(request)
    return JSONResponse(cloud.sync_on_start())


@app.get("/api/dismissed")
def dismissed_list():
    """Jobs you've dismissed, with why/when — and whether the block is permanent
    (same posting) or a temporary content-only match that will expire."""
    return JSONResponse({"items": store.list_dismissed(),
                         "count": store.dismissed_count(),
                         "content_block_days": store.CONTENT_BLOCK_DAYS})


@app.post("/api/dismissed/restore")
async def dismissed_restore(request: Request):
    """Undo a dismissal — the job becomes eligible again on the next run."""
    _check_origin(request)
    body = await request.json()
    key = body.get("dedupe_key") or ""
    if not key:
        raise HTTPException(400, "dedupe_key required")
    if not store.restore_dismissed(key):
        raise HTTPException(404, "not dismissed")
    return JSONResponse({"ok": True, "count": store.dismissed_count()})


@app.get("/dismissed")
def dismissed_page():
    return FileResponse(str(WEB / "dismissed.html"))


@app.post("/api/items/{item_id}/takeover")
async def takeover(item_id: int, request: Request):
    """Re-open this application PRE-FILLED in a visible browser window.

    'Open & apply' hands you a fresh, empty form — the bot filled it in a
    headless browser, so none of that work is visible to you. Take-over redoes
    the fill in a window you can see, then leaves it open at the point where a
    human is needed (CAPTCHA / odd question). You solve it, hit submit, then
    press 'I sent it'. This is what makes CAPTCHA-gated boards usable.
    """
    _check_origin(request)
    it = store.get_item(item_id)
    if not it:
        raise HTTPException(404, "no such item")
    if manager.busy():
        raise HTTPException(409, "a run is active — cancel it first")
    prof = store.get_profile()
    if not prof or not prof.get("cv_path"):
        raise HTTPException(400, "profile/CV not set up")
    ok = manager.start_takeover(item_id)
    if not ok:
        raise HTTPException(409, "could not start take-over")
    store.mark_assist(item_id)
    return JSONResponse({"ok": True, "message": "Opening a window, pre-filled…"},
                        status_code=202)


@app.post("/api/items/{item_id}/answers")
async def save_answers(item_id: int, request: Request):
    """Save screening answers. Learned once -> auto-filled on every future run,
    which is what stops the same question blocking us again."""
    _check_origin(request)
    body = await request.json()
    answers = body.get("answers") or {}
    learned = 0
    for question, answer in answers.items():
        if not str(answer).strip():
            continue
        store.learn_answer(question, str(answer))
        learned += 1
    if learned:
        _cloud_bg(cloud.push_answers)
    # Re-queue the item so the next prepare picks up the new answers.
    if body.get("requeue", True):
        store.transition_item(item_id, ["needs_input", "failed"], "queued",
                              reason="answers saved — will retry")
    return JSONResponse({"ok": True, "learned": learned})


@app.get("/healthz")
def healthz():
    """Liveness for launchd / uptime checks. Public on purpose: no data."""
    return JSONResponse({"ok": True})


@app.get("/api/health")
def api_health():
    """Every way this has broken before, as a list of rows with fixes."""
    return JSONResponse({**health.report(), "scheduler": scheduler.status(),
                         "sources": health.sources(),
                         "queue": store.queue_age_report(),
                         "funnel": store.funnel_counts()})


@app.get("/status")
def status_page():
    return FileResponse(str(WEB / "status.html"))


@app.post("/api/run-now")
async def run_now(request: Request):
    """Stage a batch immediately (the phone's 'Run now')."""
    _check_origin(request)
    run_id = scheduler.stage_now()
    if run_id is None:
        active = store.get_active_run()
        if active:
            raise HTTPException(409, f"a run is already active (#{active['id']})")
        return JSONResponse({"ok": True, "run_id": None,
                             "detail": store.get_setting(scheduler.LAST_STAGING_RESULT)})
    return JSONResponse({"ok": True, "run_id": run_id}, status_code=201)


@app.get("/api/cv/variants")
def cv_variants():
    """The role CVs and which one a sample posting would get."""
    from . import cv_tailor
    variants = store.list_cv_variants()
    return JSONResponse({
        "variants": [{k: v[k] for k in ("name", "label", "pages", "is_default", "tags")}
                     for v in variants],
        "recent": [{"title": a["title"], "company": a["company"],
                    "cv": a.get("cv_variant") or "general"}
                   for a in store.recent_applications(8)],
    })


@app.get("/today")
def today_page():
    return FileResponse(str(WEB / "today.html"))


@app.get("/api/today")
def api_today():
    """Everything the Today screen shows, in one object."""
    from . import today as today_mod
    return JSONResponse(today_mod.snapshot())


@app.post("/api/ask")
async def api_ask(request: Request):
    """The console: questions answered from the database, never invented."""
    from . import console
    body = await request.json()
    return JSONResponse(console.ask(body.get("q") or ""))


@app.get("/api/ask/questions")
def api_ask_questions():
    from . import console
    return JSONResponse({"questions": [{"key": k, "label": label}
                                       for k, label, _ in console.QUESTIONS]})


@app.post("/api/send-ready")
async def api_send_ready(request: Request):
    """Send everything already prepared and waiting.

    Items staged by the morning search live in a DRY run, which can never send.
    This moves the chosen ones into a fresh LIVE run and confirms them, which
    is the only path from 'the bot filled it' to 'it was submitted'.
    """
    _check_origin(request)
    body = await request.json() if await request.body() else {}
    wanted = body.get("item_ids")
    ready = [i for i in store.assist_queue(1000) if i["state"] == "ready"]
    if wanted:
        ready = [i for i in ready if i["id"] in set(wanted)]
    cap = int(body.get("limit") or 10)
    ready = ready[:cap]
    if not ready:
        return JSONResponse({"ok": True, "sending": 0, "detail": "nothing is ready"})
    run_id = store.create_run_atomic({"channels": ["ready"], "mode": "live"}, "live")
    if run_id is None:
        active = store.get_active_run()
        raise HTTPException(409, f"a run is already active (#{active['id'] if active else '?'})")
    moved = store.move_items_to_run(run_id, [i["id"] for i in ready])
    n = 0
    for item in store.list_items(run_id, ["ready"]):
        if store.transition_item(item["id"], ["ready"], "sending"):
            store.add_event(run_id, "item.state", "sending", item_id=item["id"],
                            data={"state": "sending"})
            n += 1
    if n:
        _ensure_send_worker(run_id)
    else:
        store.update_run(run_id, status="done", message="nothing to send")
    return JSONResponse({"ok": True, "run_id": run_id, "moved": moved, "sending": n},
                        status_code=202)


@app.get("/applications")
def applications_page():
    return FileResponse(str(WEB / "applications.html"))


@app.get("/api/applications")
def api_applications(stage: str = "", limit: int = 200):
    """Everything sent, with its current stage and what is due."""
    apps = store.list_applications(stage or None, limit)
    due = {a["id"] for a in store.followups_due()}
    for a in apps:
        a["followup_due"] = a["id"] in due
        a["days_since_sent"] = int((time.time() - (a.get("sent_at") or 0)) / 86400)
    return JSONResponse({"applications": apps, "funnel": store.funnel_counts(),
                         "stages": list(store.STAGES)})


@app.post("/api/applications/{app_id}/stage")
async def api_set_stage(app_id: int, request: Request):
    """Record what happened: replied, screen, interview, offer, rejected."""
    _check_origin(request)
    body = await request.json()
    stage = (body.get("stage") or "").strip()
    if not store.set_stage(app_id, stage, (body.get("note") or "").strip()):
        raise HTTPException(400, f"unknown stage or application: {stage}")
    return JSONResponse({"ok": True, "application": store.get_application(app_id),
                         "history": store.app_events(app_id)})


@app.post("/api/applications/{app_id}/followup")
async def api_followup(request: Request, app_id: int):
    """Mark a follow-up as sent (by Yonatan — the app never sends one) or
    snooze it for another week."""
    _check_origin(request)
    body = await request.json()
    if body.get("snooze"):
        store.snooze_followup(app_id, int(body.get("days") or 7))
        return JSONResponse({"ok": True, "snoozed": True})
    store.add_app_event(app_id, "followup", (body.get("note") or "").strip())
    store.snooze_followup(app_id, 7)
    return JSONResponse({"ok": True, "logged": True})


@app.get("/api/applications/{app_id}/history")
def api_history(app_id: int):
    return JSONResponse({"history": store.app_events(app_id)})


@app.get("/api/answers/gaps")
def answer_gaps(limit: int = 60):
    """The questions blocking the most applications right now."""
    gaps = store.answer_gaps(limit)
    return JSONResponse({"gaps": gaps,
                         "blocked_items": sum(g["blocking"] for g in gaps),
                         "answered": len(store.list_answers())})


@app.post("/api/answers/bulk")
async def save_answers_bulk(request: Request):
    """Answer several screening questions at once and retry what they blocked."""
    _check_origin(request)
    body = await request.json()
    answers = body.get("answers") or {}
    # Collect what each question blocks BEFORE learning it: once an answer
    # exists the question is no longer a gap, so the items would be invisible.
    gaps = {g["label"]: g["item_ids"] for g in store.answer_gaps(500)}
    learned = requeued = 0
    for question, answer in answers.items():
        if not str(answer).strip():
            continue
        before = store.recall_answer(question)
        store.learn_answer(question, str(answer).strip())
        if store.recall_answer(question) == before:
            continue                      # refused (credentials, IDs, blank)
        learned += 1
        requeued += store.requeue_items(gaps.get(question, []),
                                        "answer saved — retrying")
    if learned:
        _cloud_bg(cloud.push_answers)
    return JSONResponse({"ok": True, "learned": learned, "requeued": requeued})


@app.get("/answers")
def answers_page():
    return FileResponse(str(WEB / "answers.html"))


@app.get("/api/answers")
def list_answers():
    return JSONResponse({"answers": store.list_answers()})


@app.post("/api/runs/{run_id}/items/{item_id}/skip")
async def skip_item(run_id: int, item_id: int, request: Request):
    _check_origin(request)
    store.transition_item(item_id, ["ready", "needs_input", "failed"], "skipped",
                          reason="skipped by user")
    store.add_event(run_id, "item.state", "skipped", item_id=item_id,
                    data={"state": "skipped"})
    return JSONResponse({"ok": True})


# ------------------------------- SSE ---------------------------------------

@app.get("/api/runs/{run_id}/events")
async def events(run_id: int, request: Request, cursor: int = 0):
    last_id = request.headers.get("last-event-id")
    if last_id and last_id.isdigit():
        cursor = int(last_id)

    async def gen():
        nonlocal cursor
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            rows = store.events_after(run_id, cursor, limit=200)
            for e in rows:
                cursor = e["id"]
                data = {"type": e["type"], "message": e["message"],
                        "item_id": e["item_id"], "level": e["level"],
                        "data": json.loads(e["data_json"] or "{}")}
                yield (f"id: {e['id']}\nevent: {e['type']}\n"
                       f"data: {json.dumps(data)}\n\n")
            run = store.get_run(run_id)
            if run and run["status"] in ("done", "cancelled", "error") \
                    and not store.events_after(run_id, cursor, 1):
                yield f"event: end\ndata: {json.dumps({'status': run['status']})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
