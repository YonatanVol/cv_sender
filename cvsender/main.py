"""FastAPI app for CV Sender v2 — JSON + SSE API and the served UI.

The confirm endpoints trigger real, irreversible outward actions, so the server
binds to loopback only (config.HOST) and mutating routes check the Origin.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import config, cv as cvmod
from .core.run_manager import manager
from .db import store
from .db.migrations import migrate

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"

app = FastAPI(title="CV Sender v2")


@app.on_event("startup")
def _startup():
    migrate()
    swept = store.sweep_stale_runs(config.STALE_RUN_S)
    if swept:
        print(f"[startup] recovered stale runs: {swept}")


app.mount("/data2", StaticFiles(directory=str(config.DATA_DIR)), name="data2")
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


# --------------------------- consent / origin ------------------------------

def _check_origin(request: Request) -> None:
    """Reject cross-origin mutations of the irreversible endpoints."""
    origin = request.headers.get("origin")
    if origin is None:
        return  # same-origin fetch / curl without Origin
    allowed = {f"http://{config.HOST}:{config.PORT}",
               f"http://localhost:{config.PORT}"}
    if origin not in allowed:
        raise HTTPException(403, "cross-origin request rejected")


# ------------------------------- pages -------------------------------------

@app.get("/")
def index():
    return FileResponse(str(WEB / "index.html"))


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
    return JSONResponse({"ok": True, **meta})


# -------------------------------- runs -------------------------------------

@app.post("/api/runs")
async def create_run(request: Request):
    _check_origin(request)
    body = await request.json()
    options = {
        "channels": body.get("channels") or ["greenhouse"],
        "mode": "live" if body.get("mode") == "live" else "dry",
        "cap": max(1, min(int(body.get("cap", 20)), 100)),
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
    return JSONResponse(store.get_active_run() or {})


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
