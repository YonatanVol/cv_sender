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

## It runs itself

Install once and the app starts at login, restarts if it crashes, comes back
after a reboot, and stages a fresh batch every morning:

```bash
bash scripts/install_launchd.sh --remote   # --remote also serves your phone
```

The scheduler lives **inside the server** (`cvsender/scheduler.py`): one thread,
one browser, one run at a time. It stages every morning at 08:30, catches up
until 20:00 if the Mac was asleep, and tops the queue up to your target. It only
ever **prepares** — sending stays behind your confirm.

When something breaks, one command says what and how to fix it:

```bash
./.venv/bin/python -m cvsender.doctor
```

```
CV Sender — OK
  ✓ profile            Yonatan Volsky · Yonatan_Volsky_CV.pdf
  ✓ browser engine     chromium-1228
  ✓ linkedin session   valid for 361 day(s)
  ✓ scheduler          tick 15s ago · next staging 08:30
  ✓ auto-start         launchd job loaded
  ✓ cloud backup       connected
  ✓ secrets            cloud.json 0o600
  ✓ queue              247 ready for you · 0 sent today · LinkedIn 15 of 15 left
```

The same rows appear on **Settings → System** in the app, with a **Run now**
button. Every red row carries the exact command that fixes it — these are the
failures that actually happened: a launchd job nobody installed, a macOS update
that deleted Playwright's browser, a Supabase project that paused itself.

## Screening answers — the throughput lever

Roughly four of five LinkedIn applications stop on a screening question, so this
is where volume is won. The form reader pulls each question with the label a
human sees (LinkedIn's apply dialog is inside a shadow root, so this uses
element handles, not page-level JavaScript), including radio groups and
dropdowns.

Open **`/answers`**: every question blocking your queue, ranked by how many
postings it blocks, answered once. Saving learns the answer and re-queues every
posting that was waiting on it. Field ids, duplicated labels, EEO
self-identification and anything answerable from your profile are filtered out,
and credentials or ID numbers are never stored.

## A CV per role

One CV for every posting buries the half that matters. The same true content is
built into role versions — **backend**, **full-stack**, **qa**, **data** — that
differ only in emphasis: which three projects lead, how the skills lines are
ordered, and the one-line opener. Nothing is invented; every claim appears in
the general CV too.

The posting picks one (`cvsender/cv_tailor.py`): title words count three times,
description words once, a tie or an unclear title gets the default CV. The
choice is deterministic, so the same posting always gets the same CV. The file
actually attached is hashed into the send handle (so the changed-CV guard
compares like with like) and recorded on the application as `cv_variant`, which
is what makes reply rates comparable per CV later.

Build them from your CV sources, then they appear on **Settings → Your CV**:

```bash
cd cv_source && node build_variants.js && node build_ats.js   # per family
```

## LinkedIn volume cap

LinkedIn is the only channel that truly auto-sends, and automating it is against
its User Agreement. Sends are capped in code: `linkedin.daily_cap` (15 by
default) can be lowered from settings but never raised past
`LINKEDIN_CAP_CEILING` (20) — not by a setting, a script, or a restored cloud
backup. Over the cap an item goes back to *ready* and resumes tomorrow; nothing
is sent twice.

### Realistic throughput

CAPTCHA is near-universal on ATS boards — in one measured run **11 of 12** items
hit one, including companies never tried before. So fully-automatic sending at
volume is not attainable there; the workflow that *is*:

1. the scheduler stages a few hundred filled applications overnight
2. you clear them in bursts at `/assist` (~5–10s each, so ~15 min)
3. **"🖥 Fill it for me"** re-opens one in a visible window already filled, so you
   only clear the CAPTCHA and submit

LinkedIn Easy Apply is the one channel that genuinely auto-sends, and it is
deliberately capped and jittered for account safety.

## Phone access

The app runs on your Mac (that's where the browser automation lives) and you
drive it from your phone.

```bash
./.venv/bin/python -m cvsender.setpass     # one-time: set a passphrase
bash scripts/install_launchd.sh --remote   # always-on, survives reboots
# or, for a one-off session with a QR code to scan:
./run2.sh --remote
```

Scan the QR (or open the printed URL) on your phone, sign in, then **Add to
Home Screen**. It installs as a real app — Android Chrome needs the PNG icons
in the manifest for that, which are included.

Works on Android and iOS; the Mac must stay awake and on the same network
(or on Tailscale, below).

Because `/confirm` and `mark-sent` fire **real, irreversible** applications,
remote access is authenticated and the app enforces it in two places: `run2.sh`
refuses `--remote` without a passphrase, and the server itself refuses to bind a
non-loopback host unless one is set. Local (`127.0.0.1`) use stays open and
unchanged.

- Passphrase hashed with **scrypt** (stdlib), never stored or logged in plaintext
- Sessions are server-side random tokens, stored only as SHA-256 in the database
  with a sliding 30-day expiry, so a restart no longer logs your phone out.
  **Sign out everywhere** is on the settings page, and changing the passphrase
  signs every device out
- Mutating requests are checked against an explicit origin allow-list built from
  the machine's real addresses (plus an optional `public_origin` for Tailscale),
  never "Origin equals Host", which a DNS-rebinding page can forge
- Failed logins are rate-limited and locked out
- **From anywhere** (not just your Wi-Fi): [Tailscale](https://tailscale.com) is
  the recommended path — device-level auth and no public URL. Cloudflare Tunnel
  works if you want a public hostname.

## Cloud backup (Supabase)

Your **CV, profile, run settings and learned screening answers** are mirrored
to a free Supabase project so they survive a wipe and follow you to a new
machine. Run history stays local — it is large, machine-specific and worthless
elsewhere.

- **Local DB is the truth, the cloud is a mirror.** Every save (`PUT
  /api/profile`, `POST /api/cv`, `PUT /api/settings`, learned answers) pushes in
  a background thread; a failed push never fails the request.
- **On startup** the app bootstraps itself from the cloud if this device is
  empty, then pushes whatever is local (the CV only when its hash differs).
- **Settings → ☁ Cloud backup** shows connection status, with *Back up now*
  and *Restore from cloud* (cloud wins — for a new device or after a wipe).
- **Security.** The embedded key is the *publishable* anon key — it is not the
  gate. Every table and the private `cv` bucket are RLS-protected and only
  answer requests carrying the **owner secret** (`x-cvs-owner`), generated once
  into `data2/cloud.json` (gitignored, `chmod 600`). Anyone holding that file
  can read your CV; copy it to a new machine to adopt the same cloud data.
- **The CV is encrypted before upload** (AES-256-GCM, key derived from the
  owner secret with scrypt). RLS is not enough for a file: Supabase's CDN was
  observed serving a cached object to requests that fail RLS at the origin, so
  the stored blob must be useless on its own — and now it is.
- Restored answers pass through the same prohibited-field filter as learned
  ones, so a credential can never enter the answer bank via the cloud.
- Free tier pauses the project after ~7 idle days; the daily runner's sync
  keeps it alive, and it can be restored from the Supabase dashboard.

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
    scheduler.py     in-process morning staging + heartbeat (never sends)
    health.py        every known failure mode as a row with its fix
  web/               dashboard + assist/answers/settings PWA (vanilla JS + SSE)
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
- **Access from anywhere still needs Tailscale**, installed and signed in by
  you. On the LAN the app is plain HTTP behind the passphrase.
- **A sleeping Mac stops everything.** The service uses `caffeinate -i`, but a
  closed lid still sleeps; the doctor reports the gap rather than hiding it.
- **The queue is mostly human work.** CAPTCHA-protected boards always need a
  person; Assist mode is how that stays fast.
