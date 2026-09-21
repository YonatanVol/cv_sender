# Blockers

_Last update: 22 September 2026, 02:20._

| # | Blocker | Owner | Status | Detail |
|---|---|---|---|---|
| 1 | 149 screening questions unanswered, blocking 390 postings | Yonatan | NEEDS YONATAN | The largest group is "how many years of experience do you have with X". Those are facts only he has, and inventing a number would be lying to an employer in his name. Answer once at `/answers`; every posting waiting on that question retries automatically. Nineteen questions whose answers are stated in his CV were answered on 22 Sep and are listed in `CURRENT_STATUS.md` — all editable there. |
| 2 | 3 applications filled and ready, not sent | Yonatan | NEEDS YONATAN | Filled with the CV attached and a screenshot to check. Sending is his decision. LinkedIn's day cap has 5 sends left. |
| 3 | Greenhouse emails a verification code | External | ACCEPTED | Since 21 Sep an application is only accepted after an 8-character code mailed to the applicant is pasted back. That is a human check and will not be automated. Affected applications are parked as `needs_input` naming exactly that reason. |
| 4 | Tailscale not installed | Yonatan | NEEDS YONATAN | Needs his Mac password, a system-extension approval and his own account, so it is not something I can do. Until then the phone works on the same Wi-Fi at `http://Yonatans-Macbook-Pro-6.local:8010` — a name, not an address. |
| 5 | CAPTCHA on some job sites | External | ACCEPTED | Unsolvable by the app by design. Those postings get the assisted path: filled by the bot, cleared by a human. |
| 6 | 39 LinkedIn postings have no Easy Apply | External | ACCEPTED | External apply, on the employer's own site. They stay in the queue with a working link and can only be finished by hand. |
| 7 | Disk | Yonatan | NEEDS YONATAN | `df` reports 17 GB free of 460 GB (not the 27 GB he expected). Workable, but not much headroom. |
| 8 | Telegram notifications | Claude Code | NOT STARTED | Needs a bot token from BotFather. Nothing else blocks it. |
| 9 | Feedback labels on cards | Claude Code | NOT STARTED | good fit / wrong profession / too senior as buttons feeding the score. |
| 10 | A manual-QA role passed the filter | Claude Code | OPEN | "בודק/ת תוכנה" was sent on 22 Sep. Manual QA without development deserves the same gate the non-software titles already have. |
| 11 | One application recorded its company as "LinkedIn" | Claude Code | OPEN | The card's employer name fell back when the subtitle was missing, so the tracker row is unhelpful. Cosmetic, but it is in the record of a real application. |
