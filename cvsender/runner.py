"""Self-driving runner — keeps the assist queue stocked without an agent.

Runs entirely on deterministic rules (no LLM anywhere), so staging applications
costs nothing and behaves identically every time. Point cron/launchd at it and a
day's applications are prepared before you open the app; you then clear the
queue in bursts.

    python -m cvsender.runner --target 100          # stage up to 100
    python -m cvsender.runner --target 100 --loop   # top up as you clear them

It only ever PREPARES (fill + attach CV + park). It never submits: sending stays
behind the human confirm, which is also what keeps LinkedIn usage defensible.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import config
from .core.run_manager import manager
from .db import store
from .db.migrations import migrate

ATS = ["greenhouse", "lever", "ashby", "comeet"]


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def queue_depth() -> int:
    return len(store.assist_queue(limit=1000))


def wait_for_run(run_id: int, timeout_s: float = 1800) -> str:
    """Block until the run settles. Returns its final status."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        run = store.get_run(run_id)
        st = run["status"] if run else "gone"
        if st in ("awaiting_confirm", "done", "error", "cancelled", "interrupted"):
            return st
        time.sleep(4)
    return "timeout"


def stage_batch(cap: int, channels: list[str], geography: str, strictness: str,
                concurrency: int) -> tuple[str, int]:
    """Run one prepare cycle. Returns (status, items_added)."""
    active = store.get_active_run()
    if active:
        _log(f"a run is already active (#{active['id']}) — cancelling it")
        manager.request_cancel(active["id"])
        time.sleep(3)
    options = {"channels": channels, "mode": "dry", "cap": cap,
               "geography": geography, "strictness": strictness,
               "concurrency": concurrency}
    run_id = store.create_run_atomic(options, "dry")
    if run_id is None:
        return "busy", 0
    manager.start_prepare(run_id, options)
    status = wait_for_run(run_id)
    counts = store.item_counts(run_id)
    return status, sum(counts.values())


def run(target: int, loop: bool, channels: list[str], geography: str,
        strictness: str, concurrency: int, batch: int, sleep_s: float) -> int:
    migrate()
    store.sweep_stale_runs(config.STALE_RUN_S)
    store.sweep_stuck_items(config.STUCK_ITEM_S)

    prof = store.get_profile()
    if not prof or not prof.get("email") or not prof.get("cv_path"):
        _log("ERROR: set up your profile + CV first (open the app).")
        return 2

    while True:
        depth = queue_depth()
        _log(f"assist queue: {depth} finishable · sent today: {store.sent_today()}")
        if depth >= target:
            _log(f"target of {target} already staged — nothing to do.")
            if not loop:
                return 0
        else:
            need = target - depth
            cap = min(batch, need)
            _log(f"staging up to {cap} more (need {need})…")
            status, added = stage_batch(cap, channels, geography, strictness,
                                        concurrency)
            new_depth = queue_depth()
            _log(f"run {status}: queue {depth} -> {new_depth} "
                 f"(+{new_depth - depth})")
            if new_depth <= depth:
                # Nothing new is reachable — usually every remaining candidate is
                # already staged or deduped. Backing off beats hammering boards.
                _log("no new applications found; stopping to avoid churn.")
                if not loop:
                    return 0
        if not loop:
            return 0
        _log(f"sleeping {int(sleep_s)}s…")
        time.sleep(sleep_s)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", type=int, default=100,
                   help="how many finishable applications to keep staged")
    p.add_argument("--batch", type=int, default=40, help="max staged per cycle")
    p.add_argument("--loop", action="store_true", help="keep topping up")
    p.add_argument("--sleep", type=float, default=900, help="seconds between cycles")
    p.add_argument("--channels", default=",".join(ATS + ["linkedin"]))
    p.add_argument("--geography", default="israel_remote")
    p.add_argument("--strictness", default="balanced")
    p.add_argument("--concurrency", type=int, default=config.PREPARE_CONCURRENCY)
    a = p.parse_args(argv)
    try:
        return run(a.target, a.loop, [c for c in a.channels.split(",") if c],
                   a.geography, a.strictness, a.concurrency, a.batch, a.sleep)
    except KeyboardInterrupt:
        _log("stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
