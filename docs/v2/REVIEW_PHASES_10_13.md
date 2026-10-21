# Review: Phases 10–13 and demo mode

An independent agent reviewed `0de67416..46e5f52e` (cockpit, Web Push, outbox, learning and certificates, commissions, Pulse, demo mode) and wrote throwaway tests to confirm three findings. It found no cross-org access or authentication bypass. Every finding below is fixed with a test unless marked otherwise.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | `Commission.lead` was `PROTECT`, so deleting a person or an org that had a commission returned 500 (V1 account deletion too) | `SET_NULL` (`commissions/0002`); the record survives its lead. Test deletes a user and an org |
| 2 | Medium | Demo sign-in could delete a real org that used the slug `demo`, and any user on the demo email domain | Wipe only an org marked `demo` and users with `provider="demo"`; a real org on the slug returns 409 and is never touched |
| 3 | Medium | A demo visitor could change the owner's email and break reset for good, then keep the account through forgot-password | Demo accounts can't change profile, password or delete themselves (403), forgot-password never mails them, wipe works by account not email |
| 4 | Medium | The offline outbox could send one person's queued messages as another person on a shared browser | Rows carry the writer's id; flush sends only the signed-in person's rows; sign-out clears the queue |
| 5 | Medium | A path-completion certificate could rest on self-ticked quiz steps | Quiz steps complete only with a passing attempt; issuing re-checks it |
| 6 | Medium | Pulse evaluations and AI quiz drafting skipped the AI budget cap, and Pulse ignored its flag | Budget checked before a run, before each case and before drafting (429); every Pulse endpoint honours the `pulse` flag (501) and the nav hides it |
| 7 | Medium/Low | An evaluation could stay "running" forever when the queue was off or a case crashed | Queue refusal marks the run failed (501); any exception marks it failed |
| 8 | Low | Unlimited quiz attempts returned the number of right answers, so the key could be mapped | A failed attempt returns only "not passed" and the pass mark; 5 attempts a day |
| 9 | Low | Team leads saw org-wide governance and evaluation figures in the Pulse overview | Left out of the team view |
| 10 | Low | DM push ignored offboarded recipients and types switched off entirely; subscriptions survived sign-out | Active members only; `enabled=False` stops push; sign-out unsubscribes the browser |
| 11 | Low | `POST /cohorts` with a non-list returned 500 | 400 with a clear message |
| 12 | Low | `$` in currency, model and colour checks let a trailing newline through | `fullmatch` |
| 13 | Low | Two first demo sign-ins at once could 500 | One builder at a time (503 "being built" for the other) |
| 14 | Low | An admin could record or approve their own commission | Only someone else (or the owner) can |
| 15 | Low | SSO return always landed on `/w/flolabs` | Lands on the person's first workspace |
| 16 | Low | Public certificates showed internal project and tag names, and broke on key rotation | Names only when the issuer ticks "include details"; verification uses the key the certificate names, with retired keys in `CERTIFICATE_PREVIOUS_PUBLIC_KEYS` |
| 17 | Note | `next` after sign-in was not validated (pre-existing) | Only `/w/…` paths are followed |

Not changed: certificate verification stays public whatever the `public_portfolio` flag says, because a verifier must be able to check it (TECH_DEBT). The demo still relies on `DEMO_MODE` plus the `flobrain.W010` warning.
