"""FastAPI app: the local dashboard with the one-click Run button."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .apply import runner

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="CV Sender")
db.init_db()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Serve screenshots / uploaded files for the results page.
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")


def _run_in_progress() -> bool:
    latest = db.get_latest_run()
    return bool(latest and latest["status"] == "running")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "profile": db.get_profile(),
        "latest": db.get_latest_run(),
        "counts": db.application_counts(),
        "running": _run_in_progress(),
    })


@app.get("/profile", response_class=HTMLResponse)
def profile_form(request: Request):
    return TEMPLATES.TemplateResponse(request, "profile.html", {
        "profile": db.get_profile() or {},
    })


@app.post("/profile")
async def save_profile(
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form("Israel"),
    region: str = Form("Israel"),
    linkedin: str = Form(""),
    github: str = Form(""),
    portfolio: str = Form(""),
    needs_sponsorship: str = Form("on"),
    work_authorized_israel: str = Form("on"),
    cv: UploadFile = File(None),
):
    existing = db.get_profile() or {}
    cv_path = existing.get("cv_path")
    if cv and cv.filename:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = DATA_DIR / "cv.pdf"
        dest.write_bytes(await cv.read())
        cv_path = str(dest)
    db.save_profile({
        "full_name": full_name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "location": location.strip(),
        "region": region.strip(),
        "linkedin": linkedin.strip(),
        "github": github.strip(),
        "portfolio": portfolio.strip(),
        "needs_sponsorship": 1 if needs_sponsorship else 0,
        "work_authorized_israel": 1 if work_authorized_israel else 0,
        "cv_path": cv_path,
    })
    return RedirectResponse("/", status_code=303)


@app.post("/run")
def start_run(
    submit: str = Form(None),
    cap: int = Form(20),
    use_ats: str = Form(None),
    use_linkedin: str = Form(None),
    geography: str = Form("israel_remote"),
):
    if _run_in_progress():
        return RedirectResponse("/", status_code=303)
    options = {
        "submit": bool(submit),
        "cap": max(1, min(int(cap), 100)),
        "use_ats": bool(use_ats),
        "use_linkedin": bool(use_linkedin),
        "geography": geography,
    }
    run_id = db.create_run()
    threading.Thread(
        target=runner.execute_run, args=(run_id, options), daemon=True
    ).start()
    return RedirectResponse("/", status_code=303)


@app.get("/status")
def status():
    latest = db.get_latest_run()
    return JSONResponse(latest or {})


@app.get("/results", response_class=HTMLResponse)
def results(request: Request):
    latest = db.get_latest_run()
    return TEMPLATES.TemplateResponse(request, "results.html", {
        "latest": latest,
        "items": (latest or {}).get("stats", {}).get("items", []),
        "needs_review": db.list_applications(status="needs_review"),
    })


# ---------------------------- follow-up tracker -----------------------------

FOLLOWUP_AFTER_DAYS = 7  # highlight applications silent this long


@app.get("/tracker", response_class=HTMLResponse)
def tracker(request: Request):
    import time as _time
    apps = db.list_tracked()
    now = _time.time()
    for a in apps:
        ref = a.get("stage_at") or a.get("created_at") or now
        a["days_in_stage"] = int((now - ref) // 86400)
        a["needs_followup"] = (
            a.get("stage") in ("applied", "followed_up")
            and a["days_in_stage"] >= FOLLOWUP_AFTER_DAYS
        )
    tracked = [a for a in apps if a.get("stage")]
    stats = {
        "sent": len(tracked),
        "waiting": sum(1 for a in tracked
                       if a["stage"] in ("applied", "followed_up")),
        "followup": sum(1 for a in tracked if a["needs_followup"]),
        "interviews": sum(1 for a in tracked
                          if a["stage"] in ("interview", "offer")),
    }
    return TEMPLATES.TemplateResponse(request, "tracker.html", {
        "apps": apps, "stats": stats, "stages": db.STAGES,
    })


@app.post("/tracker/{app_id}/stage")
def tracker_set_stage(app_id: int, stage: str = Form(...),
                      note: str = Form("")):
    db.set_stage(app_id, stage, note)
    return JSONResponse({"ok": True})


@app.post("/tracker/{app_id}/note")
def tracker_add_note(app_id: int, note: str = Form(...)):
    db.add_event(app_id, note)
    return JSONResponse({"ok": True})
