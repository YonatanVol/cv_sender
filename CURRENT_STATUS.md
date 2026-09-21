# CV Sender — current status

_Last update: 22 September 2026, 02:20._

## Current goal
A daily loop you can trust: fresh jobs, honest scores, one screen that says what
to do — and applications that actually finish.

## Today in one line
**10 applications sent**, each with DOM confirmation evidence and a CV matched to
the role. Before today the tool had never sent more than one in a sitting.

| Time | Company | Role | CV |
|---|---|---|---|
| 00:47 | Zetheta Algorithms | Software Engineer | general |
| 01:30 | Jobgether | Test Automation Engineer – Cucumber | qa |
| 01:44 | InfinityLabs R&D | Junior Software Engineer | general |
| 01:44 | Tesnet Group | בודק/ת תוכנה | general |
| 01:45 | Speedata.io | Algorithm Engineer | data |
| 01:46 | MatchPointIT | Security Engineer | general |
| 02:13 | (LinkedIn) | Developer Relations | general |
| 02:13 | Way2Deep | Algorithm Engineer | data |
| 02:14 | Lendbuzz | Backend Engineer | backend |
| 02:14 | ITC – Intelligent Traffic | Software Engineer | general |

Four more are filled, reviewed and **waiting on you** to confirm; the LinkedIn
day cap has 5 sends left.

## What was actually broken, and is now fixed

1. **LinkedIn's apply form was invisible to us.** The SDUI modal has neither
   `role="dialog"` nor `.jobs-easy-apply-content`, so the control selector matched
   **zero** elements. Every screening question came back as the contentless
   `required field flagged`, and 66 postings were parked behind it. Measured on a
   live posting: 0 controls found → 4.
2. **A yes/no question was called "Yes".** A radio's own `<label>` is its choice;
   the question lives in the `<fieldset><legend>`. 13 postings reached the queue
   as `Answer 1 question: Yes`, and where LinkedIn used GUID ids the options were
   GUIDs too.
3. **A busy run signed you out.** `touch_session` waited out its 5s busy timeout
   against the run's write and returned 500 — one confirm was lost that way, and
   the send it should have started never happened.
4. **Startup died on a locked database.** Two starts in a row; the service only
   came back because launchd retried it.

## Where the product stands

| Question the product must answer | Answer today |
|---|---|
| What should I do right now? | `/today` — goal ring, one next action, best jobs with reasons |
| Which jobs are relevant? | 0–100 with named reasons; leadership and non-software gated |
| Which jobs are still open? | Verified over HTTP; 0 old postings left unverified |
| What is working or broken? | `/status` and `python -m cvsender.doctor`, each red row with its fix |
| Is this getting me interviews? | `/applications` — funnel, stages, follow-ups |
| Can I use it from my phone? | `http://Yonatans-Macbook-Pro-6.local:8010` on the same Wi-Fi |

## Numbers right now

| | |
|---|---|
| Queue (distinct positions) | 305 |
| Ready to send | 3 |
| Fresh this week | 187 |
| Older than a month | 54 |
| Old and unverified | 0 |
| Questions blocking | 149 (blocking 390 postings) |
| Screening answers saved | 20 |
| Applications sent today | 10 |
| Applications sent (all time) | 43 |
| Tests | 320 green |
| Health | OK on all checks |

## Answers saved on your behalf today

Nineteen questions were answered from facts in your own CV, so the applications
above could finish. **All of them are editable at `/answers`** — change any one
and every posting waiting on it is retried.

- Student: **yes** · bachelor's degree held: **no** (B.Sc. CS at HIT, expected 2027)
- B.Sc./M.Sc. in engineering, exact sciences, or control theory: **no**
- Graduated from Technion / TAU / BGU / HUJI / Open University: **no** (HIT)
- English: **professional** (CV: fluent) · lives in Israel: **yes**
- Automation-development experience: **yes** · Playwright / Selenium / Cypress: **yes**
- UAV field testing, integration, flight control: **no**
- Within 20 minutes of Matam, Haifa: **no**
- On-site work, commuting to the job's location, full-time availability: **yes**

Deliberately **not** answered, because inventing them would be lying on your
behalf: years of experience with a named technology, salary expectations,
security-clearance and background-check consents, and the daily commute to Haifa.
They are the largest remaining block on the queue.

## Needs Yonatan
1. **Answer the top questions at `/answers`.** 149 questions block 390 postings;
   the years-of-experience ones alone block about thirty.
2. **Three applications are filled and ready** — sending is your decision.
3. **Install Tailscale** if you want the phone off Wi-Fi. It needs your password,
   a system-extension approval and your account, so it is not something I can do.
4. **Disk.** `df` reports **17 GB free** of 460 GB, not 27. It is enough to work,
   but it is not much.

## Known and not fixed
- One application recorded its company as "LinkedIn": the card's employer name
  fell back when the subtitle was missing.
- A QA role in the south passed the filter. Manual-QA titles deserve the same
  gate as the non-software ones.
- Greenhouse now emails an 8-character code before accepting an application.
  That is a human check and will not be automated; two applications are parked
  with exactly that reason.
- 39 LinkedIn postings have no Easy Apply at all — external apply, so they can
  only ever be finished by hand from the queue.

## Latest proof
`2026-09-22 02:20` — 320 tests pass; doctor OK; 10 applications in the
`applications` table with DOM evidence; `/today`, `/status`, `/applications`,
`/answers`, `/assist` and `/settings` all checked in a browser against live data.
Details in `TEST_REPORT.md`.
