"""Ping every board token in data/boards.yaml and report job counts.

Use this to prune dead/invalid tokens and see how many relevant junior roles
each company currently has.

Run:  python scripts/verify_boards.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from app.sources import FETCHERS  # noqa: E402
from app import filtering  # noqa: E402

boards = yaml.safe_load((ROOT / "data" / "boards.yaml").read_text()) or {}

grand_total = grand_relevant = 0
for source, tokens in boards.items():
    if source not in FETCHERS:
        continue
    fetch = FETCHERS[source]
    print(f"\n=== {source} ===")
    for token in (tokens or []):
        jobs = fetch(token)
        relevant = [j for j in jobs if filtering.relevance(j)[0]]
        grand_total += len(jobs)
        grand_relevant += len(relevant)
        flag = "ok " if jobs else "DEAD"
        print(f"  [{flag}] {token:<22} {len(jobs):>4} jobs  "
              f"{len(relevant):>3} junior-relevant")

print(f"\nTOTAL: {grand_total} jobs, {grand_relevant} junior-relevant")
