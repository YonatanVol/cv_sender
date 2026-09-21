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
