"""Cloud sync (Supabase): CV file, profile, settings and learned answers.

Why only these: the engine's run history is large, machine-local and worthless
on another device, but your CV and settings are exactly what you want available
everywhere — and what hurts to lose. So those sync; runs stay local.

Security model: the publishable anon key is safe to ship, but it is NOT the
gate. Every table and the storage bucket are RLS-protected and only readable by
a request that presents the owner secret in `x-cvs-owner`. That secret is
generated once, stored locally in data2/cloud.json (gitignored) and never
committed. Treat it like a password: anyone holding it can read your CV.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Optional

import httpx

from . import config
from .db import store

CLOUD_FILE = config.DATA_DIR / "cloud.json"
BUCKET = "cv"
TIMEOUT = 20.0

# Publishable (anon) key — safe to embed; RLS + the owner secret are the gate.
DEFAULT_URL = "https://ntvuxtvepmqzdcxphurj.supabase.co"
DEFAULT_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIs"
                "InJlZiI6Im50dnV4dHZlcG1xemRjeHBodXJqIiwicm9sZSI6ImFub24iLCJp"
                "YXQiOjE3ODY4NzM2MDksImV4cCI6MjEwMjQ0OTYwOX0."
                "L1KRiiLCgwOp6fSrpvEfxV4vSdJ-pff0GpU2RnXCqAk")


def load_config() -> dict:
    """Local cloud config; creates an owner secret on first use."""
    if CLOUD_FILE.exists():
        try:
            cfg = json.loads(CLOUD_FILE.read_text())
        except Exception:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("url", DEFAULT_URL)
    cfg.setdefault("anon_key", DEFAULT_ANON)
    cfg.setdefault("enabled", True)
    if not cfg.get("owner"):
        cfg["owner"] = secrets.token_urlsafe(24)     # the actual credential
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CLOUD_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_FILE.write_text(json.dumps(cfg, indent=2))
    try:
        CLOUD_FILE.chmod(0o600)                      # it holds the owner secret
    except Exception:
        pass


def enabled() -> bool:
    return bool(load_config().get("enabled"))


def _headers(cfg: dict, extra: Optional[dict] = None) -> dict:
    h = {"apikey": cfg["anon_key"],
         "Authorization": f"Bearer {cfg['anon_key']}",
         "x-cvs-owner": cfg["owner"]}
    if extra:
        h.update(extra)
    return h


# ------------------------------- profile -----------------------------------

PROFILE_KEYS = ["full_name", "email", "phone", "location", "linkedin", "github",
                "portfolio", "cv_name", "cv_sha256", "cv_size", "cv_pages"]


def push_profile() -> bool:
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    p = store.get_profile() or {}
    row: dict[str, Any] = {"owner": cfg["owner"]}
    for k in PROFILE_KEYS:
        row[k] = p.get(k)
    row["needs_sponsorship"] = bool(p.get("needs_sponsorship"))
    row["work_authorized_il"] = bool(p.get("work_authorized_il", 1))
    row["cv_path"] = f"{cfg['owner']}/cv.pdf" if p.get("cv_path") else None
    try:
        r = httpx.post(f"{cfg['url']}/rest/v1/app_profile", timeout=TIMEOUT,
                       headers=_headers(cfg, {
                           "Content-Type": "application/json",
                           "Prefer": "resolution=merge-duplicates"}),
                       json=row)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def pull_profile() -> Optional[dict]:
    cfg = load_config()
    if not cfg.get("enabled"):
        return None
    try:
        r = httpx.get(f"{cfg['url']}/rest/v1/app_profile", timeout=TIMEOUT,
                      headers=_headers(cfg),
                      params={"owner": f"eq.{cfg['owner']}", "select": "*"})
        if r.status_code >= 300:
            return None
        rows = r.json()
        return rows[0] if rows else None
    except (httpx.HTTPError, ValueError):
        return None


# ------------------------------ settings -----------------------------------

def push_settings(pairs: dict) -> bool:
    cfg = load_config()
    if not cfg.get("enabled") or not pairs:
        return False
    rows = [{"owner": cfg["owner"], "key": k, "value": str(v)}
            for k, v in pairs.items()]
    try:
        r = httpx.post(f"{cfg['url']}/rest/v1/app_settings", timeout=TIMEOUT,
                       headers=_headers(cfg, {
                           "Content-Type": "application/json",
                           "Prefer": "resolution=merge-duplicates"}),
                       json=rows)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def pull_settings() -> dict:
    cfg = load_config()
    if not cfg.get("enabled"):
        return {}
    try:
        r = httpx.get(f"{cfg['url']}/rest/v1/app_settings", timeout=TIMEOUT,
                      headers=_headers(cfg),
                      params={"owner": f"eq.{cfg['owner']}",
                              "select": "key,value"})
        if r.status_code >= 300:
            return {}
        return {row["key"]: row["value"] for row in r.json()}
    except (httpx.HTTPError, ValueError):
        return {}


# --------------------------------- CV --------------------------------------

def upload_cv(path: str) -> bool:
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    p = Path(path)
    if not p.exists():
        return False
    obj = f"{cfg['owner']}/cv.pdf"
    try:
        r = httpx.post(f"{cfg['url']}/storage/v1/object/{BUCKET}/{obj}",
                       timeout=60.0,
                       headers=_headers(cfg, {"Content-Type": "application/pdf",
                                              "x-upsert": "true"}),
                       content=p.read_bytes())
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def download_cv(dest: str) -> bool:
    """Restore the CV from the cloud (new machine, or after a wipe)."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    obj = f"{cfg['owner']}/cv.pdf"
    try:
        r = httpx.get(f"{cfg['url']}/storage/v1/object/{BUCKET}/{obj}",
                      timeout=60.0, headers=_headers(cfg))
        if r.status_code >= 300 or not r.content.startswith(b"%PDF-"):
            return False
        d = Path(dest)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(r.content)
        return True
    except httpx.HTTPError:
        return False


def status() -> dict:
    cfg = load_config()
    ok, err = False, ""
    if cfg.get("enabled"):
        try:
            r = httpx.get(f"{cfg['url']}/rest/v1/app_profile", timeout=10,
                          headers=_headers(cfg),
                          params={"owner": f"eq.{cfg['owner']}", "select": "owner"})
            ok = r.status_code < 300
            if not ok:
                err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            err = type(e).__name__
    return {"enabled": bool(cfg.get("enabled")), "connected": ok,
            "url": cfg.get("url"), "error": err}


# ----------------------------- answers -------------------------------------

def push_answers(rows: Optional[list[dict]] = None) -> bool:
    """Sync learned screening answers so a new device inherits them."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    if rows is None:
        rows = store.list_answers()
    payload = [{"owner": cfg["owner"], "question": r["question"],
                "answer": r["answer"], "uses": int(r.get("uses") or 0)}
               for r in rows if r.get("question") and r.get("answer")]
    if not payload:
        return True
    try:
        r = httpx.post(f"{cfg['url']}/rest/v1/app_answers", timeout=TIMEOUT,
                       headers=_headers(cfg, {
                           "Content-Type": "application/json",
                           "Prefer": "resolution=merge-duplicates"}),
                       json=payload)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def pull_answers() -> list[dict]:
    cfg = load_config()
    if not cfg.get("enabled"):
        return []
    try:
        r = httpx.get(f"{cfg['url']}/rest/v1/app_answers", timeout=TIMEOUT,
                      headers=_headers(cfg),
                      params={"owner": f"eq.{cfg['owner']}",
                              "select": "question,answer,uses"})
        return r.json() if r.status_code < 300 else []
    except (httpx.HTTPError, ValueError):
        return []


# ------------------------------- restore -----------------------------------

def restore(overwrite: bool = False) -> dict:
    """Pull CV, profile, settings and answers from the cloud into this device.

    With overwrite=False (startup) only fills what is missing locally, so a
    fresh machine bootstraps itself and an existing one is never clobbered.
    With overwrite=True (explicit "Restore from cloud") the cloud wins.
    """
    out = {"profile": False, "cv": False, "settings": 0, "answers": 0}
    local = store.get_profile() or {}

    remote = pull_profile()
    if remote and (overwrite or not local.get("email")):
        fields = {k: remote.get(k) for k in
                  ("full_name", "email", "phone", "location", "linkedin",
                   "github", "portfolio")}
        fields["needs_sponsorship"] = 1 if remote.get("needs_sponsorship") else 0
        fields["work_authorized_il"] = 0 if remote.get("work_authorized_il") is False else 1
        store.save_profile(fields)
        out["profile"] = True

    local_cv = local.get("cv_path")
    have_cv = bool(local_cv) and Path(local_cv).exists()
    if remote and remote.get("cv_path") and (overwrite or not have_cv):
        dest = config.CV_DIR / "cv.pdf"
        if download_cv(str(dest)):
            store.save_profile({"cv_path": str(dest),
                                "cv_name": remote.get("cv_name") or "cv.pdf",
                                "cv_sha256": remote.get("cv_sha256"),
                                "cv_size": remote.get("cv_size"),
                                "cv_pages": remote.get("cv_pages")})
            out["cv"] = True

    for k, v in pull_settings().items():
        if overwrite or store.get_setting(f"run.{k}") is None:
            store.set_setting(f"run.{k}", v)
            out["settings"] += 1

    for row in pull_answers():
        if overwrite or not store.recall_answer(row["question"]):
            store.learn_answer(row["question"], row["answer"])
            out["answers"] += 1
    return out


def sync_on_start() -> dict:
    """Startup: bootstrap from the cloud if this device is empty, then push
    whatever is local so the cloud is never behind. Never raises."""
    try:
        restored = restore(overwrite=False)
        local = store.get_profile() or {}
        pushed = {"profile": push_profile(), "answers": push_answers()}
        # Upload the CV only if the cloud copy differs (or is missing).
        remote = pull_profile() or {}
        if local.get("cv_path") and Path(local["cv_path"]).exists() and \
                remote.get("cv_sha256") != local.get("cv_sha256"):
            pushed["cv"] = upload_cv(local["cv_path"])
            push_profile()
        return {"restored": restored, "pushed": pushed}
    except Exception as e:  # noqa: BLE001 — sync must never break the app
        return {"error": f"{type(e).__name__}: {e}"[:120]}
