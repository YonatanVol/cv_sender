"""Every way this system has actually broken, as a list of checks.

The failures so far were silent: a launchd job that was never installed, a
Supabase project that paused itself, a LinkedIn session that expired, and a
macOS update that deleted Playwright's browser. Each one only surfaced when
someone went looking. These checks turn all of them into one red row.

Read-only: nothing here starts, stops or fixes anything.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from . import config, scheduler
from .db import store

OK, WARN, FAIL = "ok", "warn", "fail"


def _row(name: str, state: str, detail: str, fix: str = "") -> dict:
    return {"check": name, "state": state, "detail": detail, "fix": fix}


def browser_engine() -> dict:
    """Both binaries, because every run here is headless.

    Caches get cleaned — the macOS 27 update took ~/Library/Caches/ms-playwright
    with it, and on 2026-09-22 it went again. Checking only
    `chromium.executable_path` reported a green row while the headless shell was
    missing and every run died with "Executable doesn't exist": a false green
    that costs a whole batch. Playwright launches the shell for headless work, so
    the check has to see the file that actually runs.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
    except Exception as e:
        return _row("browser engine", FAIL, f"{type(e).__name__}: {e}"[:120], INSTALL)
    if not path or not Path(path).exists():
        return _row("browser engine", FAIL, "Chromium is missing", INSTALL)
    ver = next((part for part in Path(path).parts
                if part.startswith("chromium")), Path(path).parent.name)
    shell = headless_shell(Path(path))
    if shell is None:
        return _row("browser engine", FAIL,
                    "the headless shell is missing — every run fails to launch",
                    INSTALL)
    return _row("browser engine", OK, ver)


INSTALL = "./.venv/bin/python -m playwright install chromium"


def headless_shell(chromium_exe: Path) -> Path | None:
    """The chrome-headless-shell binary beside this Chromium, or None.

    It lives in a sibling of the chromium-<rev> directory, named
    chromium_headless_shell-<rev>; the executable inside is named per platform,
    so it is found rather than spelled out.
    """
    root = next((p for p in chromium_exe.parents
                 if p.name.startswith("chromium-")), None)
    if root is None:
        return None
    shell_dir = root.parent / root.name.replace("chromium-", "chromium_headless_shell-")
    if not shell_dir.is_dir():
        return None
    return next((f for f in shell_dir.rglob("chrome-headless-shell")
                 if f.is_file()), None)


def linkedin_session() -> dict:
    """Read the cookie expiry off disk — never an unattended visit to LinkedIn."""
    db = config.LINKEDIN_PROFILE_DIR / "Default" / "Cookies"
    if not db.exists():
        return _row("linkedin session", WARN, "never logged in",
                    "./.venv/bin/python scripts/li_v2_login.py")
    try:
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "cvs_cookies.tmp"
        shutil.copy2(db, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        row = con.execute("SELECT expires_utc FROM cookies WHERE host_key LIKE "
                          "'%linkedin%' AND name='li_at'").fetchone()
        con.close()
        tmp.unlink(missing_ok=True)
        if not row:
            return _row("linkedin session", FAIL, "logged out",
                        "./.venv/bin/python scripts/li_v2_login.py")
        left = row[0] / 1_000_000 - 11_644_473_600 - time.time()
        days = int(left // 86400)
        if left <= 0:
            return _row("linkedin session", FAIL, "expired",
                        "./.venv/bin/python scripts/li_v2_login.py")
        return _row("linkedin session", OK if days > 7 else WARN,
                    f"valid for {days} day(s)")
    except Exception as e:
        return _row("linkedin session", WARN, f"unreadable: {type(e).__name__}")


def launchd_job() -> dict:
    """The historical failure: a plist written but never installed."""
    plist = Path.home() / "Library/LaunchAgents/com.cvsender.server.plist"
    if not plist.exists():
        return _row("auto-start", FAIL, "not installed — the app will not come "
                    "back after a reboot", "bash scripts/install_launchd.sh")
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
        if "com.cvsender.server" in out:
            return _row("auto-start", OK, "launchd job loaded")
        return _row("auto-start", WARN, "installed but not loaded",
                    "launchctl load ~/Library/LaunchAgents/com.cvsender.server.plist")
    except Exception as e:
        return _row("auto-start", WARN, f"{type(e).__name__}")


def scheduler_row() -> dict:
    """Judged by the last beat recorded in the database, not by this process:
    the doctor usually runs in a terminal while the server ticks elsewhere."""
    s = scheduler.status()
    if not s["enabled"]:
        return _row("scheduler", WARN, "disabled")
    age = s["last_tick_age_s"]
    if age is None:
        return _row("scheduler", FAIL, "never ticked — is the server running?",
                    "bash scripts/install_launchd.sh")
    if age > 10 * scheduler.TICK_S:
        return _row("scheduler", FAIL, f"stalled: last tick {age}s ago",
                    "bash scripts/install_launchd.sh")
    if age > 3 * scheduler.TICK_S:
        return _row("scheduler", WARN, f"last tick {age}s ago")
    return _row("scheduler", OK, f"tick {age}s ago · next staging "
                f"{s['next_staging_at']} · {s['last_staging_result'] or 'no run yet'}")


def cloud_row() -> dict:
    from . import cloud
    st = cloud.status()
    if not st["enabled"]:
        return _row("cloud backup", WARN, "disabled")
    if st["connected"]:
        return _row("cloud backup", OK, "connected")
    return _row("cloud backup", FAIL, st.get("error") or "unreachable",
                "the free project pauses after 7 idle days — restore it in the "
                "Supabase dashboard")


def secrets_row() -> dict:
    f = config.DATA_DIR / "cloud.json"
    if not f.exists():
        return _row("secrets", WARN, "no cloud.json yet")
    mode = oct(f.stat().st_mode & 0o777)
    return _row("secrets", OK if mode == "0o600" else WARN,
                f"cloud.json {mode}",
                "" if mode == "0o600" else f"chmod 600 {f}")


def queue_row() -> dict:
    from .engine import worker
    depth = len(store.assist_queue(limit=1000))
    gaps = store.answer_gaps(200)
    blocked = sum(g["blocking"] for g in gaps)
    detail = (f"{depth} ready for you · {store.sent_today()} sent today · "
              f"LinkedIn {worker.linkedin_cap_left()} of "
              f"{worker.linkedin_daily_cap()} left")
    if gaps:
        detail += f" · {len(gaps)} question(s) blocking {blocked}"
    return _row("queue", OK if depth else WARN, detail,
                "open /answers" if gaps else "")


def profile_row() -> dict:
    p = store.get_profile() or {}
    cv = p.get("cv_path")
    if not p.get("email"):
        return _row("profile", FAIL, "no profile", "open /settings")
    if not cv or not Path(cv).exists():
        return _row("profile", FAIL, "CV file missing", "upload it on /settings")
    return _row("profile", OK, f"{p.get('full_name')} · {Path(cv).name}")


def sources() -> list[dict]:
    """Per-board discovery health from the last run that fetched."""
    import json
    raw = store.get_setting("health.sources")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    at = data.get("at")
    out = []
    for key, row in sorted((data.get("sources") or {}).items()):
        status, jobs = row.get("status"), row.get("jobs", 0)
        ok = status == 200
        out.append({"source": key, "state": OK if (ok and jobs) else
                    WARN if ok else FAIL,
                    "jobs": jobs, "status": status, "at": at})
    return out


CHECKS = (profile_row, browser_engine, linkedin_session, scheduler_row,
          launchd_job, cloud_row, secrets_row, queue_row)


def report() -> dict:
    rows = []
    for check in CHECKS:
        try:
            rows.append(check())
        except Exception as e:                      # a check must never 500
            rows.append(_row(check.__name__, WARN, f"{type(e).__name__}: {e}"[:120]))
    worst = FAIL if any(r["state"] == FAIL for r in rows) else \
        WARN if any(r["state"] == WARN for r in rows) else OK
    return {"state": worst, "checks": rows, "at": time.time()}


def main() -> int:
    """python -m cvsender.doctor — the same rows, on a terminal."""
    rep = report()
    mark = {OK: "✓", WARN: "!", FAIL: "✗"}
    print(f"\nCV Sender — {rep['state'].upper()}\n")
    for r in rep["checks"]:
        print(f"  {mark[r['state']]} {r['check']:<18} {r['detail']}")
        if r["fix"] and r["state"] != OK:
            print(f"      fix: {r['fix']}")
    print()
    return 1 if rep["state"] == FAIL else 0
