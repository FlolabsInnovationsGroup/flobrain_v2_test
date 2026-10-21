# Security review checklist (Phase 16, before the first external customer)

Each line is checked by a person who did not write the code, against the running staging stack. Tick it and add the date and your name, or link the TECH_DEBT item that explains why it waits.

## Identity and sessions
- [ ] Passwords: V2 sign-in, reset (1 hour, one use) and first-login all work; reset tokens are stored hashed.
- [ ] A password change ends the other sessions (access and refresh tokens minted before it are refused).
- [ ] SSO (OIDC): state, nonce, PKCE and the browser-bound one-time code; an enforced-SSO org refuses password sign-in on V1 and V2 except the owner break-glass.
- [ ] SCIM: token works only for verified domains of its own org and dies with the owner who made it.
- [ ] Demo mode is off in every non-local environment (`DEMO_MODE` unset, no `flobrain.W010` warning in the logs).
- [ ] Platform admins: list reviewed; impersonation is read-only, time-limited, audited per request and visible to the org.

## Access control
- [ ] Every org-scoped endpoint returns 404 or 403 for a member of another org (the permission test matrix in CI).
- [ ] Owner-only keys (`exports.memory`, `policy.manage`, `sso.manage`) can't be granted and aren't covered by the platform-admin bypass.
- [ ] Direct messages and private groups can't be read by owners or admins, including through search, Ask, exports and the public API.
- [ ] Team leads see their own teams' time and Pulse numbers only; time descriptions follow each person's privacy choice.
- [ ] Seats: inviting past the subscription's seats returns `seat_limit`.

## Data
- [ ] No secret in the repo, images or logs (`git grep` for keys; log sampling).
- [ ] Customer AI keys, OAuth and connector tokens are encrypted (`CREDENTIALS_ENCRYPTION_KEY`) and never returned.
- [ ] Exports and personal downloads: owner or self only, 5-minute presigned links, files purged daily.
- [ ] Deletion requests erase messages with their vectors; retention deletes with vectors; audit rows are never deleted.
- [ ] Certificates verify after a signing key rotation (old public key in `CERTIFICATE_PREVIOUS_PUBLIC_KEYS`).
- [ ] Backups: RDS automated backups on, a restore was tested this quarter.

## Network and input
- [ ] Outbound calls (webhooks, connectors, SSO discovery, BYOK) go through the pinned SSRF-safe client: https, public IPs only.
- [ ] Web Push endpoints are limited to known push services; payloads carry no message text.
- [ ] Uploads: size and type limits, private bucket, no public ACLs.
- [ ] CORS lists only the real website origins; cookies are not used for API auth.
- [ ] Rate limits on sign-in, reset, demo, exports, quiz attempts and AI calls; the AI budget cap blocks platform-key calls.
- [ ] Prompt injection: retrieved documents are wrapped and quoted as data; AI writes are proposals that need a person's approval.

## Website
- [ ] No `dangerouslySetInnerHTML` on user content; links from data are internal paths or https only.
- [ ] `next` after sign-in accepts only `/w/…` paths.
- [ ] The offline outbox is per user and cleared on sign-out; the service worker caches no API responses.
- [ ] CSP and security headers on the website host (TECH_DEBT P5 while it stays on Vercel).

## Operations
- [ ] Dependency audit (`pip-audit`, `npm audit --omit=dev`) has no high or critical issue without a note.
- [ ] Incident process (RUNBOOK) has a named lead rotation and a channel.
- [ ] Load test (`deploy/loadtest`) met its targets on staging.
