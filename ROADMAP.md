# CV Sender — completion blitz, 21 Sep 2026

## Context

The automation works: 33 real applications sent, a service that restarts itself, a scheduler, per-role CVs, six job platforms. What does not work is **using** it. The queue holds 417 rows (277 distinct), **41% of them older than 30 days**, with no way to know which postings are still open. Scores are an unbounded signed float from six keyword rules, never explained, never shown on the card you actually act on. There is no screen that says what to do now. And every one of the 33 sent applications came from LinkedIn: **no job-site application has ever completed**.

So today is about trust and a daily loop, not new automation. Two decisions were taken with Yonatan before planning:

- **The assistant is a deterministic operations console.** No AI, no API key, no cost. Canned questions answered from the database, which also means it cannot invent a statistic. A clean seam is left if an AI layer is wanted later.
- **Order: trust the queue first, then the Today screen.** Freshness, duplicates and explainable scoring come before screens. Tracker, follow-ups and phone verification slip to tomorrow if the day runs out, documented as blockers rather than quietly skipped.

Baseline recorded before any change (Sprint 1 proof): doctor **OK** on all 8 rows, 197 tests green, working tree clean at `3de5d3f`, queue 277 distinct, 13 questions blocking 13 postings, applications 33 (all LinkedIn), 108 companies.

## Task discipline

Every task carries: **Status · Owner · Current state · Problem · Next action · Blocker · Proof · Definition of done**. A task becomes `DONE` only when proof is recorded — a test name, a command output, or a screenshot. Never because code was written.

Four documents are maintained in the repo root and updated after every completed task, no duplicates: `ROADMAP.md` (this plan, condensed), `CURRENT_STATUS.md` (the live board in the format Yonatan specified), `BLOCKERS.md`, `TEST_REPORT.md`.

## Sprint 2 — Job freshness (P0)

**Problem:** nothing records when a posting appeared or whether it still exists. Every adapter already receives a date from its API and throws it away (`updated_at`, `createdAt`, `publishedAt`, `time_updated`, `published_on`, `releasedDate`), and LinkedIn cards carry "2 weeks ago" text that is discarded in `cards_to_jobs` (`cvsender/channels/linkedin.py`).

- **Migration 008** adds to `run_items`: `first_seen_at`, `last_seen_at`, `posted_at`, `checked_at`, `liveness` (`active|stale|closed|unknown`), and `block_kind` (`captcha|question|review|error`). Columns only — the `state` CHECK is not rebuilt.
- **`Job.posted_at`** in `cvsender/channels/base.py`; each adapter parses the date it already fetches. One small parser per adapter, unit-tested from a captured payload.
- **`cvsender/freshness.py`**: `verify(item)` does a plain HTTP GET of `apply_url` (httpx, no browser) and classifies 404/410/"no longer accepting"/"position closed" as `closed`, a 200 with the form as `active`, anything else `unknown`. Closed postings go through the existing `store.dismiss(kind="closed")`, so they leave the queue and stay in history. Never deleted.
- **Queue rules** in `store.assist_queue`: hide `closed`; prefer `last_seen_at` within 7 days; anything older than 14 days must have `checked_at` newer than 24h or it is verified before being offered; older than 30 days is excluded from Today unless re-verified.
- **Scheduler** runs a verification pass over the oldest unverified items each tick, rate-limited, so the backlog drains without a burst of requests.

**Done when:** the queue shows only active or recently verified postings; a sample of 20 is manually checked and recorded in `TEST_REPORT.md`; the 173 rows older than 30 days are verified, closed or parked, with counts before and after.

## Sprint 3 — Duplicates and relevance (P0)

**Problem:** `dedupe_key` is channel-prefixed, so the same job from LinkedIn and Greenhouse is structurally two cards; `content_hash` rarely matches because LinkedIn has no description and ATS adapters use the board token as the company. Scoring is six rules in `cvsender/funnel/scoring.py` producing roughly −7…+6, and `Verdict.reason` is dropped before storage.

- **Identity key**: add `Job.identity` = company alias + normalized title + normalized location, plus canonical URL. `store.waiting_in_queue` and `assist_queue` collapse on it, so one real position is one card. Company aliases (board token → display name) live in a small table, seeded from what is already in the database.
- **Score 0–100, explainable.** `score_job` keeps its three gates and returns `Verdict(score=0..100, band, contributions=[{label, points}], review)`. Target-profile signals from the brief are added: student/intern/junior, C, C++, embedded, low-level, systems, Linux, networking, algorithms, Python, Java, backend, SQL. Negatives: senior/staff/lead/manager/architect, IT support, helpdesk, pure DevOps, manual QA without development, sales, HR.
- **Hard vs soft requirements**: "5+ years required" penalises heavily; "3 years preferred / יתרון" barely. Parsed from the words around the years phrase, not the number alone.
- **Uncertainty is `REVIEW`**, recorded in the new `block_kind` column rather than a new state, so a borderline role is no longer indistinguishable from a CAPTCHA or an unanswered question.
- **The explanation is stored and shown**: `score_json` keeps the contributions, and every card shows `86 · strong fit` with its reasons.
- **Feedback**: `job_feedback(identity, label, at)` with the eight labels from the brief. "Wrong profession" and "too senior" dismiss immediately and add a deterministic penalty for that company or title token; the rest only record. No learning loop beyond that today.

**Done when:** 30 real postings are scored and inspected by hand, recorded in `TEST_REPORT.md` with the reason each passed; the top 20 of the queue are visibly more relevant than today's; a LinkedIn and a Greenhouse copy of one real job collapse into one card in a test.

## Sprint 4 — Applications that finish (P0)

**Problem:** all 33 sent applications are LinkedIn. Greenhouse is 231 of the queue and has never produced a completed application. Measured distribution of Greenhouse blockers (rows / distinct postings):

| Blocker | Rows | Distinct | Fixable in code? |
|---|---|---|---|
| CAPTCHA present | 159 | 109 | No. Needs the assisted path. |
| No recognized form fields found | 59 | 32 | **Yes** — the likely `absolute_url` pointing off-domain, so the real form never loads. |
| Unanswered required question | 7 | 4 | Yes, via `/answers`. |
| Transient errors (detached frame, redirects, timeouts) | 6 | 6 | Partly: retry and a redirect guard. |

A second measured fact decides the order: screening questions are captured for only **7 of 225** Greenhouse items and **0 of 48** Ashby items, against 8 of 127 on LinkedIn. The `/answers` page therefore barely covers job sites at all.

- **Fix "no recognized form fields"** first (32 postings): rewrite `apply_url` to the hosted board URL when `absolute_url` leaves greenhouse.io, verified against three real boards including the two that currently redirect away.
- **Capture questions on the ATS path** the way LinkedIn now does (labels, kind, options) in `cvsender/channels/atsform.py`, so job-site questions reach `/answers`.
- **Regression fixture per root cause** (saved HTML), each with a test that fails without the fix.
- **CAPTCHA is honest, not fixed**: 109 postings will always need a human. They get a clear `block_kind=captcha` and a fast assisted path, not a pretence of automation.
- Re-run every previously blocked item; each remaining failure names a precise cause. No silent failures.

**Done when:** at least one Greenhouse application reaches ready or is completed through the assisted path with evidence; the "no recognized form fields" count drops measurably from 32 distinct; ATS questions appear on `/answers`; fixture tests pass; every remaining failure has an explicit named cause in `TEST_REPORT.md`.

## Sprint 5 — The Today screen (P0)

**Problem:** there is no screen that answers "what do I do now". `/assist` is a stateless stepper over one array, `/` is a desktop run console, and nothing joins them.

- **Extract shared front-end first**: `web/shared.css` (the palette copy-pasted into six files) and `web/shared.js` (`$`, `api`, `esc`, `toast`, header). Every new page uses it; existing pages migrate as they are touched.
- **`GET /api/today`** returns one object: goal and done today, best next action with its reason, fresh jobs with scores, ready to send, needs answers, CAPTCHA, failed, follow-ups due, completed today, health rollup, scheduler state. Built from `store.assist_queue`, `store.answer_gaps`, `health.report`, `scheduler.status`, `store.sent_today`.
- **`/today`** becomes the home page and the PWA start URL: goal line, one best next action, three best jobs with score and reason, then the attention sections. Never a wall of 277.

**Done when:** opening `/today` on the Mac and on the phone tells Yonatan what to do within five seconds, with numbers that match the database.

## Sprint 6 — The console (P0)

`/today` gains a compact question bar with buttons, all answered from the database: *why this score*, *what is blocking*, *why was nothing sent today*, *what failed*, *show C++ and systems jobs*, *which CV would you send here*, *what should I do next*. Free-text input maps to the same handlers through a small deterministic parser; anything unrecognised says so plainly instead of guessing. No AI, no fabricated numbers, and a clear seam (`cvsender/console.py`) if an AI layer is added later.

**Done when:** each question returns real data traceable to a query, and an unknown question is refused honestly.

## Sprint 7 — System status (P1)

Promote the existing doctor (`cvsender/health.py`, already 8 checks with fixes) into a `/status` page: per component the state, last success, last failure with reason, suggested fix, and a test button where safe (Run now, Re-check, Verify LinkedIn). Add per-source rows from the discovery health data that currently only exists inside a run's event stream.

**Done when:** a broken component is identifiable from the UI without opening the source.

## Sprint 8 — Tracker (P1)

`applications.status` is CHECK-locked to `'sent'` and `app_events` has never been written. Add the lifecycle (`applied → replied → screen → interview → offer → rejected/withdrawn/closed`) on the existing `stage` column, write `app_events` on every transition, and add an `/applications` page with history. Data model today; automation later.

**Done when:** every application shows one current stage and a visible history.

## Sprint 9 — Follow-ups and phone (P1)

Follow-up tasks appear in Today after 7 days with a copyable template, never auto-sent. Phone: verify the core flows over Tailscale if it is installed; otherwise verify on the LAN and record Tailscale as `NEEDS YONATAN` in `BLOCKERS.md`, since installing it needs his password and account.

## Sprint 10 — End-to-end proof

One clean run: discover → filter → score → Today → stage → answer a question → complete or verify → tracker → dashboard numbers move → status still healthy. Recorded with timestamps and outcomes in `TEST_REPORT.md`, plus the final acceptance checklist filled honestly, including anything not done.

## What is realistically in the day, and what is not

Sprints 2 to 6 are the day's real content and are what "trust the queue, then Today" buys. Sprints 7 to 10 are planned and will be attempted in order, but if the day ends first they are left working and written into `BLOCKERS.md` rather than half-built. Two items are already known to be **NEEDS YONATAN**, not blocked on code: installing Tailscale, which requires his password and account, and answering the 13 screening questions, which are personal facts I will not invent.

Explicitly not today, per the brief: native Android, paid AI answers, Beeminder, public badges, rewards, witness pages, recruiter-timing experiments, Raspberry Pi, large analytics.

## Rules for the day

Small coherent commits, each with tests. Fix root causes, not symptoms. No hidden exceptions, no empty-array fallbacks, no faked success. Run the suite after every change and a real browser check after every UI change. The LinkedIn cap (15/day, ceiling 20) and the no-credentials rule stay untouched. Anything unfinished is left working and documented with its exact blocker.

## Verification

- `./.venv/bin/python -m pytest tests/ -q` — currently 197, expected to grow; green before every merge.
- `./.venv/bin/python -m cvsender.doctor` — all rows green at the end.
- Live checks against the running service on `http://127.0.0.1:8010`, including `/today`, `/status`, `/answers`, and the phone.
- Freshness: a sample of 20 postings verified by hand against the real sites.
- Scoring: 30 real postings inspected, with each score's reasons recorded.
- Final: `CURRENT_STATUS.md` matches reality, the tree is clean, everything is pushed.
