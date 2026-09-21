# Test report

Every claim here is a command that was run and its real output. No entry is added
because code was written.

## 2026-09-21 — Sprint 1 baseline (before any change)

| What | Command | Result |
|---|---|---|
| Test suite | `./.venv/bin/python -m pytest tests/ -q` | 197 passed |
| System health | `./.venv/bin/python -m cvsender.doctor` | OK, 8/8 rows green |
| Repo | `git status --short` | clean at `3de5d3f`, 0 unpushed |
| Queue | SQLite read-only | 417 rows, 277 distinct, 108 companies |
| Queue age | SQLite read-only | ≤7d: 140 · 8–14d: 104 · 15–30d: 0 · >30d: 173 |
| Applications | SQLite read-only | 33, all LinkedIn — no job-site application has ever completed |
| Greenhouse blockers | SQLite read-only | CAPTCHA 159/109 · no form fields 59/32 · unanswered question 7/4 · transient 6/6 |
| Questions captured | SQLite read-only | LinkedIn 8/127 · Greenhouse 7/225 · Ashby 0/48 · Lever 0/4 |

## 2026-09-21 — CAPTCHA detection (Sprint 4, pulled forward)

Live Greenhouse pages inspected with Playwright:

| Page | Artifacts found | Old verdict | New verdict |
|---|---|---|---|
| bringg job page | `.grecaptcha-badge` 256×60 + its anchor iframe | CAPTCHA present | no challenge |
| anthropic / cloudflare job pages | none | CAPTCHA present | no challenge |

Six live relevant Greenhouse jobs prepared end-to-end after the fix:

| Company | Result | Evidence |
|---|---|---|
| similarweb ×3, melio | needs_input | form filled (5–6 fields), **CV attached**, **4 real screening questions captured each** |
| jfrog | needs_input | board redirects to join.jfrog.com (off-domain); the CAPTCHA was on that marketing page |
| axonius | needs_input | no form fields — off-domain page |

Before the fix all six read "CAPTCHA present" with nothing captured.
Tests: `tests/test_captcha_detection.py` — 9 cases (badge, invisible widget, checkbox,
hCaptcha, Turnstile, open challenge, plus the real Greenhouse call path). **207 passed.**

**Also found:** two July postings (cloudflare 7826916, anthropic 5223916008) now redirect
to a board root with `?error=true` — the postings are **dead**. "No recognized form fields"
is partly a dead-job symptom, which Sprint 2 freshness handles.

## 2026-09-21 — Send path hotfix

`_apply_send_result` referenced an undefined `h` (introduced in #27, never executed).
The next verified send would have raised NameError *after* the item was marked sent.
Fixed and covered by `test_a_verified_send_records_the_application_and_its_cv`. **198 passed** at that point.

## 2026-09-21 — Sprint 2: job freshness

**Verification pass over the 77 unverified postings older than 14 days** (plain HTTP, no browser):

| | Before | After |
|---|---|---|
| Queue (distinct) | 277 | 268 |
| Older than 30 days | 77 | 68 |
| Unverified and old | 77 | **0** |
| Verified dead, removed | — | **9** |

**A mistake caught by the manual sample, and what it cost.** The first pass closed 36
postings. Hand-checking six of them found four still live: the closure phrase list
contained the fragment `nie`, which matches inside ordinary words like *companies* and
*Denied*. The pattern now requires whole phrases only. All 36 were re-verified: **27 were
wrongly closed and were restored** (24 active, 3 unknown), 9 were genuinely gone. Tests
now assert that pages containing *companies*, *Denied*, *convenience* and
"We are accepting applications now" are never treated as closed.

**The nine genuinely dead** (each redirects to its board root with `?error=true`):
twilio ×2, similarweb, anthropic ×2, gitlab ×4.

Tests: `tests/test_freshness.py` — 40 cases (date parsing in four shapes, LinkedIn
relative ages in English and Hebrew including the dual form שבועיים, closure
classification, "never dismiss on a guess", queue behaviour). **239 passed.**

**Also fixed today:** the Mac had 570 MB free of 460 GB, and commands were failing with
"no space left on device". Freed ~500 MB of regenerable browser caches under
`data2/linkedin_profile` and screenshots older than 14 days; the LinkedIn login was
untouched and still valid for 357 days. The wider disk problem is Yonatan's to address.

## 2026-09-21 — Sprint 3: duplicates and explainable scoring

**Top 15 of the live queue after rescoring** (264 postings rescored; 119 would no longer
pass the balanced bar):

| Score | Band | Company | Role |
|---|---|---|---|
| 91 | excellent | Maytronics | Junior Embedded Software Engineer |
| 83 | strong | Glassix | Junior Fullstack Developer |
| 83 | strong | InfinityLabs R&D ×4 | Junior Software / Data / ML Engineer |
| 83 | strong | OnCloud | Junior Cloud Security Engineer |
| 83 | strong | ForSight Robotics | Junior Algorithm Engineer |
| 79 | strong | RAD | Java Backend Developer |
| 79 | strong | dropbox | Software Engineering Intern |
| 71 | possible | bringg, KayHut, abra, Fast Simon | Backend / Embedded Engineer |

Every one carries its reasons, e.g. `91 excellent fit — clear software role +5,
junior role +20, embedded +8, in Israel +8`.

**Scoring checks** (`tests/test_funnel.py`): 0–100 with a band; the score always equals
50 + its contributions; a hard "5+ years required" drops a job while "5 years preferred /
יתרון" keeps it; a senior title is a **gate**, so a senior posting stuffed with matching
keywords is still rejected (keyword bonuses used to outweigh the penalty); strict means
strong-fit only.

**Duplicates** (`tests/test_duplicates.py`): `Comigo.io` = `comigo`, `Acme Technologies Ltd`
= `Acme`, `(m/f/d)` and `- Remote` suffixes ignored; different role, company or city stay
separate. One job on two boards collapses to one card. Live queue 268 → **264**.

**Regression found while testing:** `store.add_item` had a fixed column list and silently
dropped `identity`, `posted_at` and `liveness`, so both the freshness work and the
duplicate collapse would have had nothing to read. Covered by
`test_add_item_persists_identity_and_freshness`. **265 passed.**

*Limitation:* queued rows do not store the job description, so this rescoring saw titles
only. Newly discovered jobs score with the description too, which is where the skill
signals (C/C++, Linux, embedded, algorithms) mostly come from.

## 2026-09-21 — Sprints 5 and 6: Today screen and console

Checked in a real browser at `http://127.0.0.1:8010/today`:

- **Goal ring** 0/3 with `264 waiting · 13 questions blocking · 15 LinkedIn sends left · 33 sent all time` — every figure matches a query.
- **Next best action**: "Answer: What is your salary expectation? — one answer unblocks 1 application."
- **Best jobs** with score, band and reasons: `91 excellent · Maytronics — Junior Embedded Software Engineer · 91 excellent fit — clear software role +5, junior role +20, embedded +8, in Israel +8`.
- **Ask**: clicking *What is blocking applications?* returned, from the database:
  "9 waiting on a screening answer; 113 need you to clear a form check; 3 failed with an
  error; 139 need the form finished by hand. The questions blocking the most: …"
- **Needs attention** and **System** sections match `/api/today`.

Console checks: `c++ jobs` → 2, `backend jobs` → 13, `embedded jobs` → 5, `python jobs` → 1.
`will I get this job?`, `what is the weather` and `sing me a song` are refused rather than
answered. Three bugs in my own console code were found and fixed while testing: a bare
`c` matched every question and every title, `c++ jobs` was not recognised at all, and a
legacy row with no `block_kind` was labelled "ready" when it was not. **276 passed.**

## 2026-09-21 — Sprint 4 completed: the Greenhouse form

**Root cause, measured.** All 32 distinct postings reporting "no recognized form fields
found" were off-domain: `absolute_url` points at the company's own careers page (coinbase,
catonetworks, stripe, jfrog…), which renders a description, an Apply button and a security
check — one input, no form. Probing the alternatives on a real coinbase posting:

| URL | Inputs | Form? |
|---|---|---|
| `job-boards.greenhouse.io/coinbase/jobs/{id}` | 1 | no — redirects to coinbase.com |
| `boards.greenhouse.io/coinbase/jobs/{id}` | 1 | no — same redirect |
| **`boards.greenhouse.io/embed/job_app?for=coinbase&token={id}`** | **56 (2 file inputs)** | **yes** |

**After the fix**, five off-domain postings prepared end-to-end: **5 of 5 reached the form**,
8–9 fields filled, **CV attached** on every one. Before: 0 of 5.

**Question labels.** The ATS reader concatenated name+id+placeholder+aria-label, producing
`question_67972490 are you legally authorized…` and `country country*`. It now reads the
label a person sees. Real output from a coinbase form: *Country*, *Location (City)*,
*School*, *Start date month*, *Title* — and a select carries its options. 27 postings were
re-queued to retry with the corrected URL. **281 passed.**

## 2026-09-21 — Sprint 8 and 9: tracker and follow-ups

`applications.stage` was written once as `applied` and never read; `app_events` was
created in migration 001 and never written in the app's life.

- **Lifecycle**: applied → replied → screen → interview → offer → rejected / withdrawn /
  closed, with every move written to `app_events` as history. An unknown stage changes
  nothing.
- **Follow-ups**: applications still `applied` after 7 days appear on Today and on
  `/applications`. The app **never sends one** — it records that Yonatan did, or snoozes
  it a week. Live: **18 applications are overdue a follow-up**, the oldest 56 days.
- **`/applications`**: funnel counts, stage buttons per application, follow-up actions,
  which CV was sent. Browser-checked: the funnel shows 33 applied and every application
  lists its stages.

Stage buttons were deliberately **not** clicked on real data during testing — marking an
application "replied" when nobody replied would put a fiction in the record. The
transitions are covered by `tests/test_tracker.py` (9 cases) instead. **289 passed.**

## 2026-09-21 — Sprint 7 and the end-to-end run

**Status page** `/status`: overall state, every component with its detail and the exact
command that fixes it, queue composition, **per-board health** (50 boards, e.g.
`ashby:openai ok 818 jobs`) which previously existed only inside a run's event stream,
and the scheduler's beat, next search and last freshness check.

**Full run through the new pipeline** (`POST /api/run-now`, run #37):

| | Before | After |
|---|---|---|
| Queue (distinct) | 245 | 301 |
| Fresh this week | 77 | 136 |
| **Ready to send** | 0 ever, on any job site | **7** |

The seven are Greenhouse postings at catonetworks and taboola, each with 5 fields filled
and **the CV attached** — the first job-site applications ever to reach ready. Blockers in
that run: 53 questions, 39 borderline-review, 1 form, 1 CAPTCHA.

**A filter gap the run exposed:** catonetworks "Software Team Leader (C)" scored **86**,
because the senior gate matched `lead` but not `Leader`. Leadership titles (leader, head,
chief, manager, director, ראש צוות, מנהל) are now gated; **6 leadership roles were found
in the live queue and removed**. Covered by seven new cases. **299 passed.**

## 2026-09-21 — Final check, and the last bug it found

Browser check of `/today` and `/status` at the end of the day showed Today saying
"50 questions blocking" while the system check said "91 question(s) blocking 287".
Cause: the snapshot asked for at most 50 gaps and then reported that limit as the total.
A screen that rounds its own numbers cannot be trusted, which is the point of this whole
day, so it now counts every blocking question and shows how many postings they hold up.
Covered by `test_the_question_count_is_the_real_total_not_a_page_size`. **300 passed.**

Final state: doctor OK on all 8 rows · 297 positions queued · 4 ready to send ·
91 questions blocking 287 postings · 33 applications, 5 follow-ups due · tree clean.

## 2026-09-21 (evening) — the first job-site send attempt, and what it taught

`POST /api/send-ready` moved the four prepared Greenhouse applications into a live run and
submitted them. Result: **0 sent, 4 "unverified"** — and the after-screenshot showed the
truth: the form was **still open with "Country — Select a country"**. Nothing was
submitted. Two bugs, both now fixed:

1. **"Unverified" was the wrong word.** A form that refuses the submit is not "possibly
   sent"; nothing left the browser. `validation_errors()` reads the form's own complaints
   and the item goes back to the queue as *the form refused it: Country: required* —
   fixable in seconds instead of parked in limbo.
2. **A required dropdown nobody treats as a question.** Greenhouse validates its own
   Country select. `fill_known_selects()` answers it from the profile during prepare and
   again at send.

The same screenshot showed a third problem: the CV was attached as **`cv_data.pdf`**.
That is what the employer sees. Every variant now lives in its own folder under
`Yonatan_Volsky_CV.pdf`, guaranteed by `cv_tailor.install_variant()`. **309 passed.**
