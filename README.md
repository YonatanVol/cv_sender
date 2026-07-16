# CV Sender

One-click tool that finds **junior / student / new-grad software roles** (Israel
+ remote) and applies for you — auto-filling the application forms with your CV.

It pulls jobs from public ATS feeds (**Greenhouse, Lever, Ashby, Comeet**) and
optionally **LinkedIn Easy Apply**, then drives a real browser to fill each form.
When a form needs something it can't safely answer (CAPTCHA, a custom essay
question, an external account), it's dropped into a **"Needs you"** queue instead
of submitting junk.

## Quick start

```bash
./run.sh                       # installs deps on first run, opens the dashboard
```

Then in the browser (http://127.0.0.1:8000):

1. **Profile** → fill your details and upload your CV (PDF). Save.
2. **Dashboard** → click **Run**.
   - Leave **"Actually submit"** OFF for a safe **dry run** (fills forms, never
     sends) so you can confirm everything looks right.
   - Turn it ON to really apply.
3. **Results** → see what was submitted and finish the "Needs you" queue.

## Connecting LinkedIn (one-time)

LinkedIn needs a one-time manual login (we never store your password):

```bash
./.venv/bin/python scripts/linkedin_login.py        # opens a window; log in
```

The session is saved to `data/linkedin_profile/`, so future runs stay logged in.

> ⚠️ **LinkedIn note:** automating Easy Apply is against LinkedIn's terms and can
> get an account restricted. This tool rate-limits, runs a visible browser you
> can stop, and only submits when it can fill every required field — but use it
> at your own discretion. To play it safer, run with **"Actually submit" OFF**
> (dry run) or apply on LinkedIn manually.

## Adding more companies

Edit `data/boards.yaml` (one board token per line, grouped by ATS), then verify:

```bash
./.venv/bin/python scripts/verify_boards.py         # shows live tokens + counts
```

## Layout

```
app/
  main.py            FastAPI dashboard (Run button, profile, results)
  db.py              SQLite (profile, jobs, applications, runs)
  filtering.py       junior/student + software + Israel/remote filter
  sources/           greenhouse | lever | ashby | comeet  (public job feeds)
  apply/
    runner.py        orchestrates a run: fetch -> filter -> dedupe -> apply
    forms/generic.py label-driven ATS form filler (Playwright)
    linkedin.py      LinkedIn Easy Apply driver
data/
  boards.yaml        companies to pull from
  app.db, cv.pdf, screenshots/, linkedin_profile/
scripts/
  linkedin_login.py  one-time LinkedIn login
  verify_boards.py   check which board tokens are live
```

## Honest limits

- "Apply to every job on the internet, fully unattended" isn't realistic —
  CAPTCHAs, account-creation sites (Workday/iCIMS), and custom questions are
  routed to the **Needs you** queue.
- The relevance filter is deliberately strict (skips ambiguous/senior titles) to
  avoid spammy low-quality applications.
- LinkedIn's DOM changes often; that driver is best-effort.
