# CV Sender — current status

_Last update: 5 October 2026, 19:45._

## How it runs now
**The machine scans every hour; Yonatan sends.** That is the design he asked for
on 5 October: "runs every hour, manual by me".

- **Scanning** — every hour, 07:00–23:00, inside the server. LinkedIn first, then
  Greenhouse, Lever, Ashby and Comeet. Each new posting is scored, filled with the
  CV variant that fits the role and the address that fits the location, and
  stopped one click before Submit. Nothing is sent by a scan.
- **Sending** — the Send button on the dashboard, `http://127.0.0.1:8010/` (on the
  phone: `http://Yonatans-Macbook-Pro-6.local:8010`). It shows every ready
  application with the CV and address it will carry; nothing goes out until he
  presses it. LinkedIn's limit is 15 a day.

## Today
Four applications, each confirmed by LinkedIn's "Application sent" view:

| Time | Company | Role | CV |
|---|---|---|---|
| 19:09 | CloudTeam.ai | DevOps Engineer (FinOps oriented) | general |
| 19:09 | QED Science | Full Stack Developer | fullstack |
| 19:43 | InfinityLabs R&D | DevOps & Cloud Engineer — Entry Level | general |
| 19:43 | CarGeek | Full Stack Engineer | fullstack |

49 applications all time.

## What was broken
1. **Nothing was sent for 13 days, and nothing said so.** With no channel list
   saved, the morning run fell back to Greenhouse, Lever, Ashby and Comeet — the
   boards that stop almost every application at a CAPTCHA or an emailed code — and
   never searched LinkedIn, where all 45 earlier applications finished. Every
   health check was green throughout.
2. **LinkedIn rebuilt the apply form again** (third time in three weeks). It is
   now a native `<dialog open>` with hashed class names and React ids, and its
   yes/no questions are ARIA radios whose real inputs are invisible. The reader
   saw zero fields: the first scan returned 23 of 28 postings as "too many steps",
   nothing filled, no screenshot. Now anchored on HTML semantics rather than
   LinkedIn's names; the same 30 postings come back 29 with their real questions,
   saved answers filled in automatically.
3. **Both channels shared one cap with the boards going first**, so a scan that
   found forty Greenhouse postings left LinkedIn none. LinkedIn goes first now.

## Numbers right now

| | |
|---|---|
| Queue | 66 postings, 1 ready |
| Questions blocking | 62, holding 100 postings |
| Screening answers saved | 25 |
| LinkedIn sends left today | 11 of 15 |
| Next scan | 20:23 |
| Tests | 379 green |

## Answers saved on his behalf today
From facts in his CV, all editable at `/answers`:
- Built a back-end API that talks to a database — **yes** (FastAPI over
  SQLite/Postgres; a booking platform with nine database migrations)
- Built a TypeScript front-end feature against a back-end API — **yes**
  (Next.js/React/TypeScript booking platform with Stripe)
- Background in coding or IT — **yes**
- Comfortable in a hybrid setting — **yes** (consistent with the saved on-site
  and commuting answers)

Deliberately left for him: "Do you have a bachelor's degree … **or equivalent
hands-on experience**" — with his experience a flat no would undersell him, and
yes is his call — plus years with a named technology, salary, driver's licence,
background-check consent and the training-programme commitment.

## Needs Yonatan
1. **Answer the top questions at `/answers`.** "How many years with C++" alone
   holds five postings. Each answer unblocks every posting waiting on it.
2. **Press Send** on the dashboard when something is ready. The one ready now is a
   Greenhouse posting (Taboola), which will stop at Greenhouse's emailed code.
3. **Tailscale**, if the phone should work off Wi-Fi.

## Known and not fixed
- On Greenhouse, the choices of "How did you hear about this job?" ("Glassdoor",
  "Careers Website", …) are read as separate questions on `/answers`.
- The LinkedIn resume step lists 44 uploaded CVs — every variant ever sent. It
  works, but the list will keep growing.
