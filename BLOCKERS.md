# Blockers

| # | Blocker | Owner | Status | Detail |
|---|---|---|---|---|
| 1 | 13 screening questions unanswered | Yonatan | NEEDS YONATAN | They are personal facts (GPA, university, availability, C/C++ level). Answer once at `/answers`; every blocked posting retries automatically. |
| 2 | Tailscale not installed | Yonatan | NEEDS YONATAN | Needs his Mac password, a system-extension approval and a Tailscale account. Until then the phone works on the LAN only. |
| 3 | Greenhouse CAPTCHA on 109 distinct postings | External | ACCEPTED | Not fixable in code and never will be. They get the assisted path (`Fill it for me` → human clears CAPTCHA → `I sent it`). |
| 4 | Greenhouse "no recognized form fields" on 32 distinct postings | Claude Code | IN PROGRESS | Suspected off-domain `absolute_url`, so the real form never loads. Sprint 4. |
| 5 | Screening questions barely captured on job sites | Claude Code | IN PROGRESS | 7 of 225 Greenhouse, 0 of 48 Ashby. The ATS path does not record labelled questions the way LinkedIn now does. Sprint 4. |
