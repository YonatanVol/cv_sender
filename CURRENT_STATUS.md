# CV Sender — current status

_Last update: 21 September 2026, end of the completion blitz._

## Current goal
A daily loop you can trust: fresh jobs, honest scores, one screen that says what to do.

## Status
`DONE` for the day's scope. Nine pull requests merged (#28–#35), 299 tests green,
working tree clean, nothing unpushed.

## Where the product stands

| Question the product must answer | Answer today |
|---|---|
| What should I do right now? | `/today` — goal, one next best action, best jobs with reasons |
| Which jobs are relevant? | 0–100 score with named reasons; leadership and non-software gated |
| Which jobs are still open? | Verified over HTTP; dead postings leave the queue, 0 old ones unverified |
| What is working or broken? | `/status` and `python -m cvsender.doctor`, each red row with its fix |
| Is this getting me interviews? | `/applications` — funnel, stages, follow-ups due |

## Numbers right now

| | |
|---|---|
| Queue (distinct positions) | 297 |
| Ready to send | 4 |
| Fresh this week | 132 |
| Older than a month | 63 |
| Old and unverified | 1 |
| Questions blocking | 91 (blocking 287 postings) |
| Applications sent (all time) | 33 |
| Follow-ups due | 5 |

## Completed today
- **Send path hotfix (#28)** — a NameError would have lost the next verified send.
- **CAPTCHA truth (#29)** — a reCAPTCHA badge is not a challenge; 137 postings were blocked by one.
- **Freshness (#30)** — dates from every board, liveness verified, dead postings out.
- **Scoring and duplicates (#31)** — explainable 0–100, one card per real position.
- **Greenhouse (#33)** — apply where the form actually is; readable question labels.
- **Today and the console (#32)** — the screen and nine questions answered from the database.
- **Tracker and follow-ups (#34)** — stages, history, follow-ups due.
- **Status page (#35)** — components, board health, scheduler; plus the leadership gate.

## Not done today, and why
- **Feedback labels** (good fit / wrong profession / too senior as buttons). The scoring
  and gates improved enough that this was the weakest remaining item; it is a small
  addition on top of `job_feedback`.
- **Notifications** (morning result, 21:00 status). Needs a Telegram bot token from
  Yonatan; nothing else blocks it.
- **Phone over Tailscale.** `NEEDS YONATAN`: installing it needs his password, a
  system-extension approval and his account. The app works on the LAN today.

## Needs Yonatan
1. **Answer the 91 blocking questions** at `/answers`. Each answer retries every posting
   waiting on it. This is the ceiling on how many applications finish.
2. **Four applications are ready to send** — they are filled with the CV attached and
   were not sent, because sending is his decision.
3. **Install Tailscale** if he wants the phone off Wi-Fi.
4. **Free disk space.** The Mac hit 570 MB free of 460 GB today and commands began
   failing; ~500 MB of our own regenerable caches were cleared, which is a reprieve,
   not a fix.

## Next three actions
1. Answer the top blocking questions, then re-run to see how many become ready.
2. Send the four ready applications (his call).
3. Feedback buttons, then notifications once a Telegram token exists.

## System health
Discovery HEALTHY (6 platforms, 50 boards) · Freshness HEALTHY · Filtering HEALTHY ·
LinkedIn HEALTHY (cap 15/day) · Greenhouse HEALTHY (7 reached ready today, first ever) ·
Database HEALTHY (schema v10) · Today HEALTHY · Console HEALTHY · Tracker HEALTHY ·
Phone LAN only · Notifications NOT CONFIGURED

## Final acceptance checklist

| Item | State |
|---|---|
| Fresh job discovery works | DONE — run #37 added 56 fresh positions |
| Dead jobs removed from active results | DONE — 9 verified dead, 27 wrongly closed restored |
| Duplicate jobs collapsed | DONE — identity across boards |
| Irrelevant roles filtered | DONE — non-software, leadership, foreign-only |
| Relevant jobs scored, with explanations | DONE — 0–100 with named reasons |
| Greenhouse blocker fixed or explained | DONE — form URL fixed; CAPTCHA honestly named |
| Screening answers retry blocked applications | DONE |
| Today shows the correct next actions | DONE |
| Assistant uses real system data | DONE — deterministic, refuses what it cannot know |
| Assistant is no longer a basic queue stepper | DONE |
| System status shows real health | DONE |
| Application stages work | DONE |
| Phone access | PARTIAL — LAN yes, Tailscale needs Yonatan |
| No secret exposed | DONE — data directory still not served |
| LinkedIn cap enforced | DONE — 15/day, ceiling 20 |
| Existing tests pass | DONE — 299 |
| New critical flows have tests | DONE — freshness, duplicates, scoring, today, console, tracker, status |
| Full end-to-end run succeeds | DONE — run #37 |
| This file matches reality | DONE |
| Tree clean, pushed | DONE |

## Latest proof
`2026-09-21` — 299 tests pass; doctor OK; run #37 staged 101 positions and produced the
first seven job-site applications ever to reach ready; `/today`, `/status` and
`/applications` checked in a browser. Details in `TEST_REPORT.md`.
