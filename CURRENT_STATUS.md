# CV Sender — current status

_Updated automatically during work. Last update: 2026-09-21, Sprint 2 start._

## Current goal
Make the queue trustworthy: only jobs that are fresh, still open, and not duplicated.

## Working on
Sprint 2 — job freshness (migration 008, posted dates, liveness verification).

## Status
`IN PROGRESS`

## Completed today
- Sprint 1 — baseline recorded (see Proof).

## In progress
- Sprint 2 — freshness fields and dead-job detection.

## Blocked
- None.

## Needs Yonatan
- Answer the 13 screening questions at `/answers` (personal facts, never invented).
- Install Tailscale on Mac + phone if access off Wi-Fi is wanted (needs his password and account).

## Next three actions
1. Migration 008 + `Job.posted_at` + per-adapter date parsing.
2. `cvsender/freshness.py` liveness verification + queue rules.
3. Verify a sample of 20 postings by hand and record the result.

## System health
- Discovery: HEALTHY (6 channels, 32 boards, ~7,300 postings reachable)
- Filtering: WORKS, but scores are unexplained (Sprint 3)
- LinkedIn: HEALTHY (session valid 357 days, cap 15/day)
- Greenhouse: DEGRADED (0 completed applications ever; see BLOCKERS.md)
- Database: HEALTHY (schema v7)
- Today screen: NOT BUILT (Sprint 5)
- Console: NOT BUILT (Sprint 6)
- Phone: LAN only (Tailscale not installed)
- Notifications: NOT CONFIGURED

## Latest proof
`2026-09-21 baseline` — doctor OK on 8/8 rows; 197 tests green; tree clean at 3de5d3f;
queue 277 distinct (417 rows, 41% older than 30 days); applications 33, all LinkedIn;
13 questions blocking 13 postings; 108 companies.
