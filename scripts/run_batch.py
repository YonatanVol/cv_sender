#!/usr/bin/env python3
"""Run an application batch from the command line (no web dashboard needed).

Examples:
    # Dry run: fill 10 LinkedIn Easy Apply forms, never submit
    ./.venv/bin/python scripts/run_batch.py --linkedin --cap 10

    # Really submit (asks for confirmation first)
    ./.venv/bin/python scripts/run_batch.py --linkedin --cap 10 --submit

    # ATS boards only (Greenhouse/Lever/Ashby/Comeet)
    ./.venv/bin/python scripts/run_batch.py --ats --cap 20
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.apply import runner  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cap", type=int, default=10,
                   help="max applications this run (default 10)")
    p.add_argument("--linkedin", action="store_true",
                   help="include LinkedIn Easy Apply jobs")
    p.add_argument("--ats", action="store_true",
                   help="include ATS boards (Greenhouse/Lever/Ashby/Comeet)")
    p.add_argument("--submit", action="store_true",
                   help="actually submit (default is a dry run: fill, never send)")
    p.add_argument("--geography", default="israel_remote")
    p.add_argument("--yes", action="store_true",
                   help="skip the confirmation prompt when using --submit")
    args = p.parse_args()

    if not args.linkedin and not args.ats:
        p.error("choose at least one source: --linkedin and/or --ats")

    if args.submit and not args.yes:
        ans = input(f"Really SUBMIT up to {args.cap} applications? [y/N] ")
        if ans.strip().lower() not in ("y", "yes"):
            print("Aborted — run again without --submit for a dry run.")
            return 1

    options = {
        "submit": args.submit,
        "cap": max(1, min(args.cap, 100)),
        "use_ats": args.ats,
        "use_linkedin": args.linkedin,
        "geography": args.geography,
    }
    mode = "SUBMIT" if args.submit else "DRY RUN"
    print(f"[{mode}] cap={options['cap']} linkedin={args.linkedin} ats={args.ats}")

    run_id = db.create_run()
    runner.execute_run(run_id, options)

    run = db.get_run(run_id) or {}
    print(f"\nRun {run_id} finished: {run.get('status')} — {run.get('message')}")
    print("Details: open http://127.0.0.1:8000/results (./run.sh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
