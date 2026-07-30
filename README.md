# CV Sender

Finds junior / student / new-grad software roles (Israel + remote) and applies
for you — filling the real application forms with your CV, then letting you
confirm before anything irreversible happens.

Two codebases live here:

| | path | status |
|---|---|---|
| **v2** (current) | `cvsender/` | active rebuild — port **8010**, `./run2.sh` |
| v1 (legacy) | `app/` | superseded, kept for reference — port 8000, `./run.sh` |

---

## Why v2 exists

v1 looked like it worked but barely sent anything. Three root causes, all fixed
in v2:

1. **It filled nothing on Greenhouse.** The form filler only queried the
   top-level document, but hosted Greenhouse pages put the form inside
   `#grnhse_iframe` — so it found zero fields and never attached the CV.
2. **It faked success.** "Submitted" was inferred by sniffing the page for
   English words like *"successfully"*, which produced **false `applied`
   records** — and since those were terminal for dedupe, a job that was never
   actually sent could never be retried.
3. **A run couldn't be stopped.** The worker was a daemon thread with no cancel
   signal, and a mid-run restart left the run wedged as `running` forever.

## How v2 works

**Two-phase pipeline.** Everything reversible happens first; the single
irreversible step is gated behind a human click.

```
discover → score → PREPARE (fill form, attach CV, screenshot) → you confirm → SEND → verify
```

- **PREPARE** never submits. It fills every field it recognises, attaches the
  CV, screenshots the ready-to-send form, and returns a verdict:
  `ready` · `needs_input` · `failed`.
- **SEND** re-fills from a durable `SendHandle` (so it survives a crash or a long
  review) and submits, then requires a **positive** confirmation signal —
  a 2xx submit response, a `/confirmation` redirect, or a structural success
  node. No signal ⇒ `sent_unverified`, **never** a fabricated `sent`.
- **Only a verified send is terminal** for dedupe. `needs_input` is a working
  queue, not a dead end.

### Assist mode — the throughput feature

Most applications don't fail, they *block*: a CAPTCHA, or a screening question
the bot won't invent an answer to. Those are already filled with your CV
attached, so `/assist` turns them into a fast queue:

- **Open & apply** → the real posting (already filled) → you clear the CAPTCHA
- **I sent it** → records a user-confirmed send (counts, dedupes, enters Tracker)
- **Screening answers are learned once** and auto-filled forever after
  (`answer_bank`), so the same question never blocks you twice

Keyboard: `Enter` = sent · `S` = skip · `O` = open. Mobile-first, installable
as a PWA.

### Design rules

- **No AI at runtime.** Matching, filling and verification are deterministic
  rules — a send costs nothing and behaves identically every time.
- **No CAPTCHA bypass.** The bot does 100% of the work and hands you a
  ready-to-click form; a human clears the CAPTCHA.
- **Never fabricate.** Unknown required question ⇒ `needs_input`. EEO questions
  only ever get *"decline to self-identify"*.
- **Never fill credentials.** Passwords, government IDs (incl. תעודת זהות) and
  financial fields are hard-refused — at read *and* write time — and an
  account-creation wall blocks the item instead.
- **One browser.** A single reused session; per item we open **pages**, not
  browsers. Headless by default.

## Quick start

```bash
./run2.sh          # installs deps on first run, opens http://127.0.0.1:8010
```

1. **Profile & CV** — fill your details, upload your CV (validated: real PDF
   magic bytes, size, page count, hashed).
2. **Run** — pick channels, geography, strictness, cap. Leave the mode on
   **DRY** for a safe rehearsal; flip to armed **LIVE** to send for real.
3. **Review** — confirm per item or *Send all ready*.
4. **Assist** (`/assist`) — clear the blocked queue.
5. **Tracker** — stage each application, with 7-day follow-up nudges.

LinkedIn needs a one-time manual login (we never see or store your password):

```bash
./.venv/bin/python scripts/li_v2_login.py
```

## Self-driving runner

Keeps the assist queue stocked without you (or an AI agent) in the loop —
deterministic rules only, so staging costs nothing:

```bash
python -m cvsender.runner --target 100            # stage up to 100
python -m cvsender.runner --target 100 --loop     # top up as you clear them
```

It only **prepares** (fill + attach CV + park). It never submits — sending always
requires your confirm. Schedule it for every morning:

```bash
cp scripts/com.cvsender.autorun.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cvsender.autorun.plist
```

### Realistic throughput

CAPTCHA is near-universal on ATS boards — in one measured run **11 of 12** items
hit one, including companies never tried before. So fully-automatic sending at
volume is not attainable there; the workflow that *is*:

1. the runner stages ~100 filled applications overnight
2. you clear them in bursts at `/assist` (~5–10s each, so ~15 min)
3. **"🖥 Fill it for me"** re-opens one in a visible window already filled, so you
   only clear the CAPTCHA and submit

LinkedIn Easy Apply is the one channel that genuinely auto-sends, and it is
deliberately capped and jittered for account safety.

## Channels

| Channel | Discovery | Form filling | Success signal |
|---|---|---|---|
| Greenhouse | public board API | enters `#grnhse_iframe` | submit XHR 2xx / `/confirmation` |
| Lever | public postings API | native `/apply` form | submit 2xx / confirmation node |
| Ashby | public posting API | React form (best-effort) | submit 2xx |
| Comeet | careers API (`uid:token`) | hosted form | submit 2xx |
| LinkedIn | logged-in search | Easy Apply modal step-machine | structural *"Application sent"* |

Boards are configured in `data2/boards.yaml` (auto-seeded on first run).

## Relevance funnel

v1 rejected any title without an explicit English junior keyword — 5,629 jobs
fetched, 11 kept. v2 **scores** instead:

- an unlabelled *"Software Engineer"* is neutral and **kept** by default
- explicit senior/lead/staff is strongly negative
- the job **description** is parsed for years-of-experience (`0-2` boosts,
  `5+` sinks)
- **Hebrew** titles and locations are first-class (ג'וניור, סטודנט, מפתח/ת,
  תל אביב …), with word-boundary matching so *International* no longer matches
  *intern*
- `strictness` = `loose | balanced | strict`

## Architecture

```
cvsender/
  main.py            FastAPI: profile/CV, runs, SSE stream, assist, tracker
  runner.py          (planned) self-driving loop
  core/
    run_manager.py   one long-lived event loop; submits runs, owns cancellation
    cancel.py        CancelToken — checked between items AND inside every wait
    sse.py           pub/sub wake-up for the event stream
  engine/
    session.py       BrowserSession singleton — one browser, reused
    worker.py        prepare / send pipelines
    answerbank.py    profile → form fields; prohibited-field refusal
  channels/          greenhouse · lever · ashby · comeet · linkedin (+ atsform)
  funnel/            scoring.py · keywords.py (bilingual)
  db/                connection · migrations (PRAGMA user_version) · store
  web/               dashboard + assist PWA (vanilla JS + SSE, no build step)
data2/               DB, CV, screenshots, LinkedIn session — all gitignored
```

**State model.** `runs` → `run_items` → append-only `run_events` (drives SSE via
an id cursor). Item states: `queued → preparing → ready|needs_input → sending →
sent|sent_unverified|failed`, plus `skipped`/`cancelled`. Dedupe uses both an
exact key (`channel:company:external_id`) and a `content_hash`, so the same role
reposted under a new id is caught.

**Cancellation & recovery.** Cancel is written durably *then* signalled
in-memory; the worker checks it between items and inside every sleep, and each
Playwright step has a hard timeout. On startup, runs whose worker died are swept
to `interrupted` — `preparing` → `queued`, `sending` → `needs_input` (**never**
auto-marked sent).

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

Covers the funnel (Hebrew, unlabelled titles, YoE parsing, senior rejection),
the state model (atomic single-run, guarded transitions, dedupe, crash
recovery), assist mode (answer reuse, prohibited-field refusal, idempotent
user-confirmed sends), and the browser session (reuse, idempotent close,
dead-context recovery).

## Honest limitations

- **LinkedIn automation is against LinkedIn's User Agreement** and can get an
  account restricted. v2 caps and jitters LinkedIn volume and hard-stops on any
  checkpoint — but the risk is real and yours to accept.
- CAPTCHA-protected boards always require a human; that's what Assist mode is
  for.
- Ashby/Comeet form filling is best-effort; unrecognised layouts route to
  `needs_input` rather than guessing.
- No authentication yet — the server binds to `127.0.0.1` only. **Auth ships
  before any remote/tunnel exposure.**
