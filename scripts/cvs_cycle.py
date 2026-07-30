"""Drive one LIVE prepare→send cycle and report. Reads state from the DB (robust
against control chars in JSON). Sends are real — use only with consent.

Usage: python scripts/cvs_cycle.py [channels] [cap]
  channels default 'linkedin'; cap default 6.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from cvsender.db import store  # noqa: E402

BASE = "http://127.0.0.1:8010"


def wait_status(rid, targets, timeout=260):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        run = store.get_run(rid)
        st = run["status"] if run else None
        if st != last:
            print(f"  [{int(time.time()-t0)}s] {st}", flush=True)
            last = st
        if st in targets:
            return st
        time.sleep(4)
    return last


def no_sending(rid, timeout=260):
    t0 = time.time()
    while time.time() - t0 < timeout:
        counts = store.item_counts(rid)
        if not counts.get("sending"):
            return True
        time.sleep(4)
    return False


def main(channels, cap):
    with httpx.Client(timeout=30) as c:
        # close any active run
        a = c.get(f"{BASE}/api/runs/active").json()
        if a.get("id"):
            c.post(f"{BASE}/api/runs/{a['id']}/cancel")
            time.sleep(1)
        r = c.post(f"{BASE}/api/runs", json={
            "channels": channels, "mode": "live", "cap": cap,
            "geography": "israel_remote", "strictness": "loose"})
        if r.status_code != 201:
            print("create failed:", r.status_code, r.text[:200]); return
        rid = r.json()["run_id"]
        print(f"LIVE run {rid} — preparing (no send yet)…", flush=True)
        wait_status(rid, ("awaiting_confirm", "done", "error"))

        ready = store.list_items(rid, ["ready"])
        print(f"\n{len(ready)} ready to send:")
        for it in ready:
            print(f"  - id={it['id']} {it['title']}")
        if not ready:
            print("nothing ready to send this cycle.")
            _report(rid); return

        print("\nCONFIRM-ALL → sending for real…", flush=True)
        c.post(f"{BASE}/api/runs/{rid}/confirm-all")
        time.sleep(3)
        no_sending(rid)
        _report(rid)


def _report(rid):
    print(f"\n=== run {rid} outcome ===")
    run = store.get_run(rid)
    print("status:", run["status"], "|", run["message"])
    print("counts:", store.item_counts(rid))
    for it in store.list_items(rid):
        ev = (it.get("confirmation_evidence") or "").replace("\n", " ")[:70]
        line = f"  [{it['state']:15}] {(it['title'] or '')[:42]}"
        if it["state"] == "sent":
            line += f"  ✅ {ev}"
        elif it.get("reason"):
            line += f"  :: {(it['reason'] or '').splitlines()[0][:50]}"
        print(line)


if __name__ == "__main__":
    chans = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["linkedin"])
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    main(chans, cap)
