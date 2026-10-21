# FloBrain V2 Changelog

Newest first. Each entry names the PR, what changed, and any V1 behaviour change.

## Local demo fixes (local, 2026-10-21)

- The demo's "Ask the org" and buddy sources work on SQLite (`KNOWLEDGE_VECTOR_STORE=json` in the demo scripts).
- Charts no longer warn about a -1 size before layout (`initialDimension` on the V2 chart containers).
- `<body>` ignores attributes that browser extensions add before React loads, so the Next.js dev badge stops counting them as issues.
- The demo ticker keeps routine command output out of the API window, so real errors stand out.
- V1 behaviour: unchanged.

## Market round: MCP hub, Slack and Teams, ZATCA and ETA, memory, evals, imports, compliance, workspace pricing (local, 2026-10-21)

Off by default behind flags, on and simulated in the demo (no network). Details in `docs/v2/features/`.

- **MCP hub** (`platform_api`, flag `mcp_hub`): FloBrain is a remote MCP server for Claude, ChatGPT and other clients: OAuth 2.1 with dynamic client registration, PKCE S256, resource binding, rotating refresh tokens with reuse detection, revoke; a consent page at `/w/oauth/consent`. New tools: knowledge search, ask a buddy, ask data, approvals, recent meetings, create task and run automation (both as approvals). Governance for outside MCP servers: per-tool allow/deny, read-only, expiry, which buddies may use them, and a redacted call log (90 days).
- **Slack and Teams** (`bridges`, flag `bridges`): buddies and Flo answer @mentions, DMs and `/flo` for linked people; approve or reject from Block Kit or Adaptive Card buttons, only by the right person; notices mirrored to DMs. Slack signatures and Teams Bot Framework JWTs are verified; outbound hosts allowlisted; linking always confirmed inside FloBrain.
- **E-invoicing and data residency** (`einvoice`, flag `einvoice`): Saudi ZATCA (UBL 2.1, hash chain, ECDSA signing, QR, onboarding with CSIDs, clearance and reporting) and Egypt ETA (document JSON, canonical serialization, an external signer or manual signing with the customer's token, submission). Sending to the authority is approved. A pinned data region now refuses AI calls to services outside it (`brain.llm.policy.check_ai`). Unverified spec details are configurable and listed in `EINVOICE.md`.
- **Buddy memory** (`buddy_memory`, flag `buddy_memory`): buddies remember short facts a person tells them, after asking; sensitive categories are never stored; people see, edit and delete everything; team memory for managers; included in the privacy export and deleted with the account.
- **Buddy evals** (`evals`, flag `buddy_evals`): evaluation sets per buddy with deterministic checks and an optional judge, run in a sandbox with no side effects; a quality gate before marketplace publishing and (when a set asks for it) before saving a buddy, with audited admin override.
- **Imports** (`imports`, flag `imports`): Slack export ZIP (channels, private channels opt-in, threads as quoted replies, people matched by email), Notion (connected pages or export ZIP), Google Drive (Takeout ZIP or files; a direct Drive listing needs the restricted `drive.readonly` scope, not requested yet). Safe unzip, preview, idempotent re-runs, undo. PDF text via `pypdf`.
- **Compliance** (`compliance`, flag `compliance`): SOC 2 and ISO 27001:2022 readiness with 19 automated checks on real data, access reviews that really revoke, evidence packages with a SHA-256 manifest, policy templates with acknowledgements, and a public trust page at `/trust/<slug>`. Readiness, never a certification claim.
- **Workspace pricing** (`billing_v2`, flag `workspace_pricing`): a flat per-workspace plan (Studio, up to 25 people) next to per-person plans, a seat cap that blocks new people with an upgrade link (never a silent charge), plan switching through Stripe, a public price calculator and a "per person or per workspace" toggle and slider on `/v2/pricing`. Sample prices until pricing is decided.
- **Shared:** 6 new apps, 8 flags, 10 permissions, nav entries, notification links, the AI allowance follows a workspace plan, seat-limit errors use one message. New migrations: `bridges/0001`, `einvoice/0001`, `buddy_memory/0001`, `evals/0001`, `imports/0001`, `compliance/0001`, `platform_api/0003`, `billing_v2/0003`. New Python packages: `pypdf==6.20.1`, `defusedxml==0.7.1` (no known vulnerabilities). The Zoho connection also asks for `ZohoBooks.invoices.READ`.
- V1 behaviour: unchanged. `/trust/*` pages bring their own chrome, like `/v2`.

## Growth round: automations, channels, data, write-back, Flo, academy, packs, voice (local, 2026-10-21)

Every feature is off by default behind its own flag, on in the demo, and simulated in the demo (no network). Details per area in `docs/v2/features/`.

- **Automations** (`automations`, flag `automations`): workflows from plain language (AI drafts, you review), triggers (schedule, room keyword, task created or blocked, meeting ended, customer conversation, signed inbound webhook), steps (AI prompt, post, task, notify, email and webhook through approval, wait for approval), 9 templates, the proactive daily brief and overdue nudges with a per-person opt-out, run history. `tick_automations` runs every minute.
- **Channels and the customer buddy** (`channels`, flags `channels`, `customer_buddy`): WhatsApp Cloud API and Telegram with signed webhooks and encrypted secrets; link your phone with a one-time code and talk to your buddies; approve or reject by reply; website chat widget (`public/v2/widget.js`, `/p/chat/<site key>`) with origin checks and rate limits; a customer inbox with drafts that wait for approval, hand-off to a person and a room; inbound voice notes are transcribed when `voice_notes` is on. Production needs Meta business verification and Telegram `setWebhook`.
- **Data buddy** (`datasets`, flag `data_buddy`): CSV/XLSX upload, Google Sheets published CSV, read-only PostgreSQL (encrypted DSN, private hosts blocked); questions in plain language become one checked SELECT (row and time limits), a chart and an answer, with the SQL shown; saved cards and weekly or monthly reports (`run_data_reports`); `data.ask` buddy tool.
- **Write-back connectors** (`integrations`, flag `write_integrations`): 23 actions across Google Workspace, Microsoft 365, Jira, HubSpot, Odoo and Zoho, each an approval-gated tool with a clear preview; OAuth with PKCE; providers stay "not set up" until their OAuth apps exist.
- **Flo and the crew** (`buddies`, flag `flo_router`): Flo routes a question to the right buddy (or two) the person may use, with attribution; Sales, Onboarding coach, Meeting and Customer buddy templates; thumbs up or down on replies; a buddy quality page (numbers only).
- **Academy, packs, ratings, AI per seat** (`growth`, `marketplace`, flags `academy`, `packs`): 8 lessons with checks and an AI coach; Education, Small business and Agency packs with a preview, one-click install and safe uninstall (an existing buddy with the same name is kept, never duplicated); marketplace ratings, version history and a staff-only "Verified" mark; the included-AI-per-seat meter on AI usage (sample numbers until pricing is set).
- **Voice notes** (`rooms`, flag `voice_notes`): record in rooms and the buddy composer, transcribed on the org's own Whisper server with Egyptian and Gulf Arabic hints, translated for each reader, audio served only to people who can read the room.
- **Shared:** `actions.plugins.register_tool` lets an app add an approval-gated tool; a tool can name its flag so buddies are not offered it while the feature is off. Room messages now include `kind` (`text` or `voice`). 9 permissions, 9 flags and new nav entries. New migrations: `automations/0001`, `channels/0001`, `datasets/0001`, `growth/0001`, `integrations/0003`, `buddies/0003`, `marketplace/0005`, `rooms/0003`.
- **Behaviour change (V2 only):** `GET /buddies/{id}` returns the public card (no prompt) to people who can use a buddy but not edit it, instead of 403.
- V1 behaviour: unchanged.

## Design: "mission control" system, V2 site and sign-in (local, 2026-10-21)

- **Design system:** new V2 tokens in `src/styles/v2-tokens.css`: night surfaces (#08070F), violet action (#7C6BFF), the aurora signature (flobrain.ai magenta #CC34FF to v2 cyan #00D4FF), signal colours with one job each (amber approval, rose blocked, green done), Space Grotesk, JetBrains Mono for numbers, IBM Plex Sans Arabic. A light theme with the same roles. Every `/w` screen picks it up. See `docs/v2/DESIGN.md`.
- **Shell:** FloLabs hand in the tools rail and sidebar, quieter nav with mono group labels, the cockpit mode switch restyled. `--fb-v2-bg` was used but never defined; it now follows the page colour.
- **Sign-in (`/w/signin`):** split layout with a still from the cockpit over the aurora horizon; the demo picker is a compact list under the form. Same fields, labels and flows as before (e2e unchanged). New copy translated in ar, tr, fr, pt.
- **V2 site (`/v2`, `/v2/pricing`):** new marketing pages built from the Claude Design boards: hero with the cockpit, layout tabs, the buddy crew, meetings, approvals, impact and privacy, devices, Arabic, security, FAQ. Product shots are images in `public/v2/shots`. Prices are samples until pricing is decided.
- V1 behaviour: unchanged. `/`, `/pricing` and `/signin` are the V1 pages as before; `/v2` has its own navigation and footer.

## Completion round: every area finished, and a demo that works end to end (local, 2026-10-21)

- **Meetings:** demo calls, recording, transcripts by speaker and the meeting assistant work without LiveKit, Whisper or the bot (`meetings/demo.py`, `DEMO_MODE` only). Action items become tasks with an assignee and due date, once (`task_id` written back). Meeting summaries are searchable (`knowledge/0005`). A "summary ready" notification. `meetings/0008` widens the bot status column (`waiting_admission` didn't fit on PostgreSQL).
- **SSO:** SAML 2.0 next to OIDC (`sso/0003_saml`, signxml), with the same domain, membership and platform-admin rules. The demo org signs in through a demo identity provider (`demo/idp.py`).
- **Insights:** `GET /orgs/{org}/me/insights` (yours only) and `GET /orgs/{org}/teams/{team}/insights` (leads: tasks, hours, meetings; never messages or AI use). "Keep my insights personal" leaves you out of team views and org analytics.
- **Rooms and chat:** room AI answers from the room's sources with citations and model choice; edit and delete your own messages; announcements with pinning; mentions notify only people who can read the room; new rooms and DMs from the UI (`rooms/0002`, `brain/0005`).
- **Tasks, time, calendar:** priority, order, due-date rules, block reasons, reminders (`tick_tasks`), templates; time categories, manual entries, weekly submit and lead approval, reports by week (`tasks/0002`, `timetracking/0002`). Team time reports are now lead/admin only; deleting a task needs its creator, the lead or an admin.
- **Docs and learning:** autosave, history and restore, conflict screen, attachments (local storage), Notion masterclasses, cohort progress for leads.
- **People and access:** directory filters, member status and role changes with confirmation, teams and projects page, pending HR members, permission requests from everyone, grant durations, audit log filters, first login asks for a phone. Fixes: admins could make someone owner; grants could cross orgs; unknown decisions counted as reject.
- **AI admin:** AI keys page, usage by member/team/model/feature with CSV export, budgets per org/team/member that stop AI, switch to a cheaper model (buddies, scheduled agents and room AI) or alert; buddy share requests; edit before approving; agent run output; Pulse agents, cost, governance and incidents tabs.
- **Platform:** outside AI agents over MCP (owner allowlist, every call approved by its person, answers kept as quoted untrusted text, offered in buddy chats), public status page with email subscriptions, webhook delivery log and test ping, Stripe checkout on the server, basic PII redaction.
- **Content Studio:** the full editor UI (transcript editing, clips, captions, formats, brand, voiceover, publishing with consent checks), render queue, calendar, working local storage, a demo render worker, sample media and a TTS provider interface.
- **Shell:** notification pop-ups, the demo runs scheduled work by itself, low-bandwidth mode, theme toggle, report a problem, Insights and Mission Control in the nav, a longer guided tour.
- **Languages:** every screen in English, Arabic, Turkish, French and Portuguese; context keys with spaces now display correctly.
- **Deploy:** Helm chart 0.2.0 (probes, autoscaling, ingress, network policies, Whisper and bot), marketplace versions and updates.
- V1 behaviour: unchanged.

## Phase 16 — privacy center and external readiness (local)

- `privacy` app (`privacy/0001_initial`): `GET/PUT /orgs/{org}/me/privacy` shows what FloBrain keeps about you in that org (counts), who can see it (your team leads by name, the visibility rules) and your choices: share time descriptions, keep personal insights to yourself, product-analytics consent.
- Time privacy: with "share what I worked on" off, team views (`/time-entries?team=`) return your entries without descriptions (`description_hidden: true`). Your own list is unchanged.
- Your data: `POST /me/data-exports` builds a zip of everything that is yours across orgs (profile, memberships, messages you wrote, tasks, time, private AI conversations, usage, notifications, skills, certificates, portfolio, quiz attempts, leads, commissions); one an hour, 5-minute download link, file purged with the other exports.
- Deletion requests: a member asks (`/privacy/deletion-requests`); admins are notified and decide (`org.members.manage`, never your own request; an owner must hand over first). Approving erases, in that org, their room messages (and search vectors), time descriptions and private AI conversations, and starts offboarding. Audited.
- Retention: the owner (`policy.manage`) sets days for messages, recordings, transcripts and time entries (7–3650, empty keeps forever); `python manage.py apply_retention` (daily; Helm cronjob and compose ticker added) deletes older data with its vectors. Nothing is deleted until a policy is saved (Q20).
- Seats: with entitlements enforced, inviting past the subscription's seats returns 409 `seat_limit`.
- Platform onboarding: `POST /platform/orgs` (platform admins) creates an org and invites its owner; reserved slugs like `demo` are refused.
- External readiness: `SECURITY_REVIEW.md` checklist, `deploy/loadtest` (Locust script and targets), incident and privacy-request sections in the RUNBOOK.
- Website: Privacy page (what we keep, who sees it, choices, download, request deletion), Retention and deletion page for admins (decide requests; owner edits retention), readable notifications with in-workspace links, tour stops for both.
- V1 behaviour: unchanged for real users. Demo accounts (provider `demo`) can no longer change their V1 profile or password.

## Load test baseline (local)

- First run of `deploy/loadtest` (50 simulated members, 3 minutes, 2 vCPUs for everything): steady endpoints p95 under 150 ms, 0.09 % errors (shared-account timer conflicts). `me/access` went from 114 queries to 11 with `org_permissions` (p95 1.1 s to 86 ms), kept equal to `can()` by a test. Sign-in bursts are CPU-bound by design. Results in `deploy/loadtest/RESULTS.md`.

## Meetings review fixes (local)

- See `REVIEW_MEETINGS.md`: one recording at a time, no stuck transcriptions, the bot reports from the lobby and obeys "Remove assistant" there, no recording without a confirmed announcement, silent fake devices, a recorder that can't hang, expiring bot requests, rooms only FloBrain creates and 10-minute join tokens, stop works when the recording already ended, streaming uploads on the Whisper service (key required) and the worker, team-scoped manager checks, strict webhook keys. `meetings/0006`.

## Meetings inside FloBrain and our own meeting assistant (local)

- Calls inside FloBrain (Q2: self-hosted LiveKit). `POST /meetings/{id}/join` gives a 2-hour token for that call and person (room access and `voice_video` required; support sessions can't join). Managers (`meeting.manage`) start and stop recording, which first posts a notice in the room and shows a banner to everyone in the call, and can end the call for all. LiveKit Egress records audio into the private bucket; the signed LiveKit webhook (`/api/v2/livekit/webhook`) adds the recording, keeping only keys under the meeting's own prefix.
- Transcription with our own Whisper service (`whisper-server/`, OpenAI-style API; `ASR_BACKEND=http|local`), as a worker job; then the summary, decisions and action items from the org's platform model under its AI policy and budget, posted to the room. Action items become tasks with one click. Recordings can also be uploaded (audio or video up to 500 MB). `meetings/0004`, `meetings/0005`.
- Our own meeting assistant (Q23: no vendor). `meeting-bot/` (Node, Playwright, Xvfb, PulseAudio, ffmpeg) claims sessions with a `meeting_bot` worker token (`workers/0002`, render and bot tokens can't use each other's endpoints), joins Meet, Teams or Zoom as "FloBrain assistant", says in the chat that it records, records audio, leaves when the meeting ends, when alone, after the time limit or when removed from FloBrain, and uploads the audio to the same pipeline. Sessions whose bot stops reporting are failed, never rejoined.
- Website: the meetings tab creates meetings, joins calls, shows recordings with transcript status and segments, the summary with decisions and action items, the assistant's status with "Remove assistant", and uploads; a call page with LiveKit's components and the recording banner. Added `livekit-client` 2.22.3 and `@livekit/components-react` 2.9.24.
- Infra (not applied): `deploy/meetings/` compose with LiveKit, Egress, Redis, Whisper and the assistant; AWS shape in `awssupport.md` 3.12. The Tauri desktop app is dropped (owner decision). V1 behaviour: unchanged.

## Pulse routing applied (local)

- Platform AI calls that don't name a model now follow the org's routing policy: the primary model, then its fallbacks (only allowlisted models, at most three tries), moving on only when the provider itself failed. Refusals and bad input are never hidden by a fallback. Customer keys and explicit models are never routed; private-only still refuses first. Every model that failed over is recorded as its own error call, and the trace says `fallback` (Pulse shows "Completed on a fallback model"). V1 behaviour: unchanged.

## Review fixes for Phases 15–16 (local)

- See `REVIEW_PHASES_15_16.md`: onboarded owners are active, `/w/` page names are reserved slugs, one locked seat check on every path that adds or reactivates someone (invite, reactivation, SCIM, HR webhook), erasure removes cached translations, analytics consent is enforced, deletion requests re-check the owner and need a real member, safer `next`, no demo passwords, https-only connector links.
- Arabic: every workspace screen is translated (about 870 phrases in `messages/ar-phrases/`, English text as the key, a test fails when a `tr("…")` string has no Arabic line or its placeholders differ). Public certificate and portfolio pages switch to right-to-left.

## Review fixes for Phases 10–13 and demo mode (local)

- See `REVIEW_PHASES_10_13.md`: commissions no longer block account or org deletion (`commissions/0002`), demo mode can't touch a real org or user, demo identities are locked, the offline outbox is per person, quiz steps need a pass, Pulse honours its flag and the AI budget, stuck evaluations fail cleanly, failed quiz attempts reveal nothing, lead Pulse views stay in their teams, DM push skips offboarded people, strict regexes, no self-approved commissions, SSO lands on your workspace, certificates survive key rotation and hide internal names by default, `next` is checked.

## Phase 15 — integrations and meeting bot (local)

- Connector SDK (`connectors` app, `connectors/0001_initial`, flag `integrations`, `integrations.manage` connects): one interface for read, write and publish connectors (`connectors/sdk.py`); a connector registers itself and gets the catalog entry, connect, sync (worker job `connectors.sync`) and disconnect for free. Network calls use the SSRF-safe pinned client. Secrets are encrypted and never returned.
- Every connection belongs to a room: imported items are visible only to people who can open that room. Disconnecting wipes the secret, marks it revoked, cancels queued syncs, and a running sync re-checks before writing; items of a disconnected source disappear from lists and task links.
- GitHub connector (fine-grained token, one repository): issues and pull requests with state (open, closed, merged), links kept only when they point at github.com; tasks link to items (`/tasks/{task}/links`), only items you can see.
- Declared but not set up (no OAuth apps yet): Google Calendar, Google Drive, Gmail, Zoom, Discord bridge, Notion. They show as "not set up yet".
- Meeting bot (`meetings/0003_meetingbotsession`, flag `meeting_bot`): invite from a meeting with `meeting.manage`, a valid Zoom/Meet/Teams link and the host's consent; a recording notice is posted to the room first; proactive answers can't be switched on, and the helper refuses them when any participant isn't an org member. No vendor adapter yet (Q23), so inviting answers "not configured".
- Website: Integrations page (connected, available, brought in with link-to-task) and "Invite assistant" on meetings. V1 behaviour: unchanged.

## Phase 13 — Pulse (local)

- `pulse` app (`pulse/0001_initial`; key `pulse.view` for admins; team leads see an overview of their teams only): overview (calls, errors, p50/p95 latency, platform cost from the price table, tokens, members' own-key calls, calls per day, governance from AI action statuses, latest evaluations), per-model table, per-surface totals, traces with filters and a detail view (ids and types only, never content). Every number is computed from `UsageEvent`, `AITrace`, `ActionProposal` and evaluation records (nearest-rank percentiles).
- Evaluations: suites of prompts with deterministic checks (must contain, must not contain, latency), run on the worker against platform models only (`pulse.eval` job), per-case results and pass rate against the suite threshold.
- Routing and failover: policy editor (primary and fallback platform models from the allowlist, latency threshold, max task cost; "AI writes need approval" can't be switched off) and a preview that explains which model a request would use from the last day's health. Never applied to customer keys; private-only always wins. Applying the policy inside the provider is TECH_DEBT.
- Alerts: error rate, p95 latency or cost over a window; `tick_pulse` notifies owners and admins once per window (and emails them when SMTP is set).
- Website: Pulse console (overview with a calls-per-day chart and screen-reader table, models, traces, evaluations, routing with preview, alerts). The demo org seeds a week of labelled demo usage.
- `AITrace.surface` gains `evaluation` and `learning` (`telemetry/0004`). V1 behaviour: unchanged.

## Phase 12 — leads and commission (local)

- `commissions` app (`commissions/0001_initial`, flag `commissions`, also switchable per member; key `commissions.manage` for owner and admins): leads with the pipeline Contacted, Meeting 1, In progress, Won, Lost (members see and move only their own); commissions recorded and changed only by `commissions.manage`, each change audited with before and after; summary of earned, pending, referrals sent and conversion rate. Amounts are validated decimals (no negatives, NaN or infinity), currencies are 3 letters.
- Website: Leads and commission page (summary, pipeline board with keyboard-friendly stage selects, commission list; admins record and change status). Home shows the commission widget when the flag is on.
- V1 behaviour: unchanged.

## Phase 11 — learning, certificates, portfolio, mentorship (local)

- `learning` app (`learning/0001_initial`, flag `learning`; keys `learning.manage`, `certificates.issue` for admins): learning paths (team-scoped, safe steps: https links, doc and quiz ids), per-person progress, quizzes (members never receive the answers; AI-drafted quizzes from a document are saved as drafts for an admin to publish), attempts and scores, mentorships (notes visible to the mentor and mentee only, not admins; the mentor sees the mentee's learning progress only), cohorts with instructor progress, Notion masterclasses as "not configured".
- Certificates (Decision 40): built from real records (hours by tag, finished tasks, projects, dates), signed with Ed25519 (`CERTIFICATE_SIGNING_KEY`; empty: 501), revocable, unguessable public id. Public, signed-out endpoints: `GET /api/public/verify/{slug}` (only the certificate data, signature check, revoked state), `GET /api/public/certificates/public-key`, `GET /api/public/portfolio/{slug}` (only items the person made public, only from orgs with `public_portfolio` on).
- Notification preferences from Phase 10 cover the seven spec sound types with preview.
- Website: Learning (paths, quizzes with a runner, certificates, portfolio, mentorship notes), public `/verify/{slug}` with a QR code, public `/p/{slug}` portfolio. `qrcode` added.
- V1 behaviour: unchanged.

## Phase 10 — cockpit modes, Arabic/RTL, PWA, low-bandwidth (local)

- `workspace` app (`workspace/0001_initial`): `GET/PUT /api/v2/me/cockpit-layout` (Default, Focus, Custom; validated panels, widgets, default room tab, accent colour; `low_bandwidth`), `PATCH /orgs/{org}/me/presence`.
- Web Push (`notifications/0002`): `GET /push/vapid-public-key`, `POST/DELETE /me/push-subscriptions` (endpoints must be a known browser push service: no SSRF), `GET/PUT /me/notification-preferences` (per type: on/off, push, sound). New DM or group messages push "New message from X" with a link and **no message text**. Sending needs `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` (empty: nothing is sent). Support-access notices can't be switched off. `pywebpush` added.
- Fix: job handlers for exports and push now register in `AppConfig.ready()`, so a separate worker process (which never loads URLs) can run them.
- Website: new home cockpit with Default/Focus/Custom, saved layout, widgets (my tasks, approvals, progress, impact, buddies, announcements, commission), accent colour; language switch with Arabic catalog for the shell, home, demo and sign-in, RTL via logical properties, SSR-safe `useLocale` (fixes a hydration mismatch); PWA manifest, icons, service worker (offline page, push, never caches API data); offline outbox for room messages (sent in order when back online); notification settings with sound preview and "turn on push".
- Not in this phase: the Tauri desktop shell (Decision 39: after the PWA is stable) and Turkish, French and Portuguese catalogs. V1 behaviour: unchanged.

## Demo mode and workspace UI for Phases 8–17 (local)

- **Demo mode** (`demo` app, `demo/0001_initial`, off by default): `DEMO_MODE=True` adds `GET /api/v2/demo`, `POST /api/v2/demo/signin {role}` and `POST /api/v2/demo/reset`, and `manage.py seed_demo`. The seed builds "Nile Labs" with an owner, admin, team lead and member, plus teams, a project, tasks, time, rooms, documents, a meeting, skills, buddies, a pending AI action, an agent, Content Studio and a marketplace listing. `DEMO_AI` answers AI calls with labelled sample replies (no key, no network) and proposes a task when asked. Runbook: `DEMO.md`.
- `GET /api/v2/orgs/{org}/me/access`: role, teams led, org-level permissions, effective flags and demo role, to drive the navigation (every endpoint still checks on its own).
- **Website:** sign-in page with SSO and the demo seat picker plus "Take the full tour"; SSO return page with the browser nonce; a new workspace shell with role-aware navigation, an approvals counter and the demo bar (switch seat, guided tour, start over); screens for Ask the org, Buddies (builder and chat), Approvals, Agents, Team reports, Content Studio, Marketplace, API and webhooks, AI policy, Billing, SSO and provisioning, Export, Support access, Platform console and the 14-stop guided tour. 501 now shows "switched off for your organization".
- V1 behaviour: unchanged. Not pushed.

## Phase 17 review fixes (local)

- Independent review: 2 High, 5 Medium, 8 Low, all fixed (`REVIEW_PHASE_17.md`).
- **V1 behaviour change (security):** V1 `POST /api/auth/signin/` returns 403 `sso_required` for members of an org with enforced SSO, and V1 refresh refuses tokens issued before the user's last password change (the cut-off V2 already used; SSO enforcement and SCIM pauses also set it). V1 chat returns 409 `private_only` only on installs with `AI_FORCE_PRIVATE_ONLY` (never on the hosted deploy).
- Owner-only keys `exports.memory`, `policy.manage`, `sso.manage`: owner seat required, not grantable, not covered by the platform-admin bypass. Admins lose `policy.manage` and `sso.manage` from their defaults.
- **Frontend contract:** `GET /api/v2/sso/start?email=&client_nonce=` (16–128 random characters kept in sessionStorage) and `POST /api/v2/sso/exchange {code, client_nonce}`.
- SSO: a new issuer or client id switches SSO off; no SSO for platform admins; issuer changes audited. SCIM: verified domains only, reactivates only SCIM-made pauses of plain members, tokens die with their owner, strict booleans.
- Stripe: paid checkouts only, ignored events not recorded, ordered by `event.created`, canceled is final (`billing_v2/0002_subscription_last_event`). Indexing follows the plan. Support sessions don't translate or move read markers. Helm and compose hardening.

## Phase 17f — sovereign package (local)

- `deploy/sovereign/`: docker-compose "open models only" profile (pgvector, migrate, gunicorn API, job worker, ticker, vLLM, TEI with BGE-M3 on an `internal` network with no route out), `Dockerfile.api` (gunicorn, non-root; the hosted `Dockerfile` is unchanged), `env.example`, a Helm chart skeleton (existing-secret env, pre-install migrate job, API, worker, cron jobs, egress `NetworkPolicy`) and a runbook. Compose validated with `docker compose config`; Helm not linted yet (tool not reachable here).
- `AI_FORCE_PRIVATE_ONLY`: every org is `private_only` without a policy row; `PUT /policy` to anything else returns 409 `locked`; the policy payload shows `locked_private_only`.
- `AI_ALLOW_PLAINTEXT_HOSTS`: the direct chat client and the embeddings client may use plain http only for hosts listed there (in-cluster names). Default empty: https only, as before.

## Phase 17e — memory export, marketplace, platform console (local)

- Memory export (`exports/0001_initial`, `exports.memory`, owner only; admins do not get it by default): `POST /orgs/{org}/exports/memory` builds a zip on the worker with team and project room messages (not deleted) and their documents, as JSON Lines + Markdown with ids, authors and times, plus `manifest.json`. Direct and group rooms, AI threads, the memory graph and personal data are excluded by construction. One running export per org, `EXPORT_MAX_PER_DAY` (3), 5-minute download links, `EXPORT_RETENTION_DAYS` (7) and `purge_exports`. Request and every download are audited. Support sessions never get a download link.
- In-org marketplace (`marketplace/0001_initial`): members offer buddies they created and templates (`marketplace.submit`); `marketplace.manage` approves or rejects, never their own listing (except the owner). The definition is frozen at submission, so later edits are not approved silently. Installing makes the installer's own private copy, checked against the installer's access (tools they lack are dropped and reported; the author's room list never travels). Templates need `content.manage` to install.
- Platform console (`console/0001_initial`), platform admins only: `GET /platform/orgs`, `GET/PUT /platform/orgs/{org}/flags` (booleans, audited with before/after), `GET/POST /platform/impersonations`, `POST …/{id}/end`.
- Impersonation: a reason (10+ characters), 5 to 60 minutes, never another platform admin. The token type is `impersonation`, so V1, refresh and the middleware ignore it; V2 accepts it only for GET/HEAD/OPTIONS under `/api/v2/orgs/<that org>/` and `/api/v2/me`, while the session is live, the admin is still a platform admin and the person is still an active member. Each request is audited with the admin as impersonator. The person and the org's owners and admins get a notification; `GET /orgs/{org}/impersonations` (`audit.view`) lists sessions with the reason, and the org can end one.
- Open: the Phase 0 platform-admin bypass still exists alongside impersonation (Q42). V1 behaviour: unchanged. Not pushed.

## Phase 17c/17d — OIDC SSO and SCIM 2.0 (local)

- New `sso` app (`sso/0001_initial`): `SSOConnection` (issuer, client id, encrypted secret, verified domains, `enabled`, `enforced`), `SSOState`, `SSOLoginCode`, `SCIMToken` (SHA-256), `SCIMGroupMap`.
- Admin (`sso.manage`, owner/admin): `GET/PUT /orgs/{org}/sso` (discovery must return the same issuer; the secret is never returned), `POST /orgs/{org}/sso/domains` and `/sso/domains/{domain}/verify` (DNS TXT `_flobrain-verify.<domain>` = `flobrain-verify=<token>`; a domain verified by another org is refused with 409). SSO cannot be enabled before a domain is verified.
- Login: `GET /api/v2/sso/start?email=` → authorize URL (PKCE S256, single-use 10-minute state, nonce). `GET /api/v2/sso/callback` verifies the ID token (JWKS signature RS256/ES256, issuer, audience, expiry, nonce, `email_verified`, verified domain, active member of that org) and redirects to `/w/sso?code=` with a single-use 2-minute code; `POST /api/v2/sso/exchange` swaps it for tokens. No tokens in URLs. SSO never creates accounts.
- `enforced`: password sign-in for that org's members returns 403 `sso_required`; the owner keeps a break-glass password login.
- SCIM 2.0 at `/scim/v2/Users` and `/scim/v2/Groups` (Bearer `scim_…`, tokens from `POST /orgs/{org}/scim/tokens`). Never grants owner, admin or lead. New users are `pending` until they join a group mapped to a team; `active=false` or DELETE pauses the membership and revokes the user's personal access tokens; the owner cannot be deactivated. Filter supports `userName eq` only.
- SAML 2.0: not built (TECH_DEBT). V1 behaviour: unchanged. Not pushed.

## Phase 17b — plans, entitlements and Stripe (local)

- New `billing_v2` app (`billing_v2/0001_initial`): `Plan` (entitlements `{flags, limits}`), `Subscription`, `UsageInvoiceLine`, `StripeEvent`. The old `customer_billing`/`payment_history`/`group_*` tables are untouched (Q37).
- `effective_flag` = plan entitlement AND org flag AND member flag, when `BILLING_ENFORCE_ENTITLEMENTS` is on and the org has a subscription (no subscription keeps today's behaviour; canceled turns plan features off; past due keeps them during grace). `renders_per_month` from the plan caps Content Studio renders.
- `POST /api/v2/billing/stripe/webhook`: signature verified (`STRIPE_WEBHOOK_SECRET`, 5-minute tolerance, constant-time compare), each event id applied once; handles checkout completion and subscription create/update/delete (plan by price id, seats, status, period end).
- Plans are written only by platform admins (`GET/POST /api/v2/platform/plans`, `PUT /api/v2/platform/orgs/{org}/subscription`) or the webhook. `GET /orgs/{org}/billing` (`billing.view`, admin) shows plan, seats used, and this month's platform model cost at cost with BYOK at zero markup.
- No checkout UI or invoice creation yet. Not pushed.

## Phase 17a — org policy and private-only mode (local)

- `organizations.OrgPolicy` (`organizations/0004_org_policy`): `inference_scope` (`external_allowed` | `private_only`), `pii_redaction`, `data_region`. `GET /orgs/{org}/policy` (members), `PUT` (`policy.manage`). PII redaction other than `off` returns 501 until the detector service exists.
- One gate, `brain.llm.policy.check_ai`, before every model call: room AI, knowledge ask and indexing, translation, buddies (and scheduled agents), Content Studio AI, MCP knowledge search, external agents. In `private_only` only hosts on `AI_SELF_HOSTED_HOSTS` may receive org content; the legacy multimodal host, external APIs, external BYOK keys and external agents get 409 `private_only` and no network call. Switching to `private_only` disables external customer keys at once.
- V1 behaviour: unchanged (V1 chat has no org). Not pushed.

## Phase 14 review fixes (local)

- Ten findings fixed (`REVIEW_PHASE_14.md`): new `rooms:write` scope for the MCP message tool; webhook sends have a 15 s total deadline and a DNS timeout and are queued after commit; deliveries are claimed once; IP literals and malformed URLs refused; bad input is 4xx; deactivation revokes tokens at once; per-user API throttle and 20 webhooks per org; `member.joined` only for active members; private post URLs never sent. Not pushed.

## Phase 14 — public API, webhooks, MCP, status page (local)

- New `platform_api` app (`platform_api/0001_initial`): `PersonalAccessToken`, `WebhookEndpoint`, `WebhookDelivery`, `ExternalAgentServer`, `Incident`. Flags `api_access`, `webhooks`, `external_agents`, `status_page` (501 when off). New keys `webhooks.manage`, `integrations.manage`, `incidents.manage` (admin).
- Tokens: `GET/POST /api/v2/me/tokens`, `DELETE /api/v2/me/tokens/{id}`. `fbp_…` shown once, SHA-256 stored, scopes `tasks:read|tasks:write|rooms:read|time:read|knowledge:read|mcp`, optional expiry (≤365 days), at most 20 active. Each request re-checks the token, the owner's active membership, a password change since issue (revokes), and `api_access`. A PAT is not accepted on `/api/v2/` and a session JWT is not accepted on the public API.
- Public API `/api/public/v1/`: `me`, `tasks` (list, get, create), `rooms`, `rooms/{id}/messages`, `time/entries` (own). Same selectors as the app (`visible_tasks`, `accessible_rooms`, `create_task`). Per-token rate limit `PUBLIC_API_RATE` (120/min).
- MCP `POST /api/mcp` (JSON-RPC 2.0): `initialize`, `ping`, `tools/list` (only tools the token's scopes allow), `tools/call`. Read tools `tasks_list`, `rooms_list`, `knowledge_search`, `time_report`; write tools `tasks_create`, `rooms_post_message` only create an approval proposal (needs `ai_actions`).
- Webhooks: `GET/POST /orgs/{org}/webhooks`, `GET/DELETE …/{id}` (with recent deliveries). HTTPS only; DNS resolved and private, loopback, link-local, reserved and IPv4-mapped addresses refused at save **and** at send; the connection is pinned to the checked address (no DNS rebinding); redirects never followed. Signing secret shown once, encrypted; header `FloBrain-Signature: t=…,v1=HMAC-SHA256`. Events `task.created`, `task.completed`, `member.joined`, `meeting.ended` (never for direct/group rooms), `content.published`; payloads carry ids only. Retries with backoff (6 attempts) on the worker; `manage.py tick_webhooks`.
- External agents: `GET/POST /orgs/{org}/external-agents` only for hosts on `EXTERNAL_AGENT_ALLOWED_HOSTS` (empty, Q24).
- Status page: org incidents (`GET/POST /orgs/{org}/incidents`, `PATCH …/{id}`) stay private to the org; only platform admins publish. `manage.py export_status --out status.json` writes the public projection (platform incidents and component states, no org data) for separate static hosting.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 9 review fixes (local)

- Independent review; two high and nine medium/low findings fixed (`REVIEW_PHASE_9.md`). Consent is checked on everything inside the render (sources and brand media). Members can add people tags but not remove them. Output and source bytes are pinned by ETag (approval hash and a re-check before posting). Approve and edit are conditional updates. OAuth connects only after the starting user confirms a one-time code (`POST /orgs/{org}/social-accounts/confirm`). Fast word-boundary checks. Started-then-cancelled renders count toward the quota. Video/audio duration is required. AI cuts may not remove speech. Bad ids are 4xx.
- Migration `content_studio/0005_review_fixes`. Not pushed.

## Phase 9e — batches, copy and voiceover interface (local)

- `POST …/content/batch`: a template plus 1–`CONTENT_BATCH_MAX_ROWS` (100) rows makes one project and one render per row; each row is validated against the template's variables (no unknown fields, length limits) and travels as `text_fields` data for the worker. The monthly render quota counts every row.
- `POST …/projects/{id}/copy`: per-platform title (100), description (platform caption limit) and up to 10 hashtags through `direct`, validated; unknown platforms in the answer are dropped.
- `POST …/content/voiceover` returns 501 until a TTS provider is chosen (Q18); the interface is in `content_studio/tts.py`.
- Phase 9 backend complete locally. Not pushed.

## Phase 9d — consent, social accounts and publishing (local)

- Models `ConsentRecord`, `AssetPerson`, `SocialAccount`, `OAuthState`, `PublishJob`; `MediaAsset.face_count` (a count from detection, never identification) (`content_studio/0004_publishing`). Flag `social_publishing` for accounts and posts.
- Consent: `GET/POST …/content/consents` (your own, or anyone with `consent.manage`), `POST …/consents/{id}/revoke` (the person or a manager). `PUT …/assets/{id}/people` tags who appears. Scopes `internal` ⊂ `public_social` ⊂ `marketing`. Every tagged person needs live consent; more detected faces than tagged people blocks.
- Social accounts: `GET …/social-accounts/platforms` (each shows configured or not; YouTube and TikTok post private until their app audit, Q16), `GET …/social-accounts` (never tokens), `POST …/social-accounts/{platform}/connect` (`social.connect`; single-use 10-minute `state`, PKCE verifier kept encrypted server-side), `GET /api/v2/oauth/callback/{platform}` (fixed redirect URI; authenticated by state only, re-checks the user is active with `social.connect`), `DELETE …/social-accounts/{id}` (wipes tokens). Tokens are AES-GCM under `CREDENTIALS_ENCRYPTION_KEY`. No live connector yet (company developer apps, Q16); `SOCIAL_SANDBOX_ENABLED` enables a local test connector.
- Publishing: members submit (`POST …/publish-jobs`, a finished render of a project they can see, a connected account) → `awaiting_approval`. `POST …/approve` needs `content.approve` and the job's current `hash` (render, output, copy, thumbnail, account, time); consent is checked at approval **and** again right before posting. Any edit resets approval. `manage.py tick_content` publishes due posts with retries (5, backoff) and notifies on failure; a changed hash or missing consent sends the job back to `awaiting_approval`. `…/cancel`, `GET …/content/calendar`.
- New tool `content.publish`: an approved AI proposal only **submits** a post; the post still needs its own approval.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 9c — edit decisions, captions and AI clips (local)

- `EditDecisionList` (versions, user or AI) and `ClipSuggestion` (`content_studio/0003_edl_clips`). `PUT …/assets/{id}/transcript` stores validated word timings.
- `GET/PUT …/projects/{id}/edl` (structured operations only: cut, keep, captions, reframe, overlay, intro, outro, music; times inside the media; cut/keep boundaries never inside a word; `base_version` prevents lost edits, 409), `POST …/edl/revert` (undo as a new version, re-validated).
- `GET …/projects/{id}/captions.srt|vtt` on the **edited** timeline.
- `POST …/suggest-clips` and `…/auto-edit` call `direct` only (501 without it, never the legacy host) with the transcript quoted as data; the JSON is validated and bad items are dropped and listed under `rejected`. Suggestions never edit; accepting a clip adds a keep range as a new version; auto-edit is a new AI version you can revert. AI send throttle, platform budget, usage `surface=content_studio`.
- Renders now freeze the latest EDL into the job spec. Not pushed.

## Phase 9b — render workers (local)

- New `workers` app: `WorkerToken` (SHA-256 hash and last4 only; `manage.py worker_token --issue NAME | --revoke ID`, the raw token is printed once). `content_studio.RenderJob`.
- `POST …/content/projects/{id}/render` (`9x16_1080`, `16x9_1080`, `1x1_1080`, or `custom` with a template) within `CONTENT_RENDERS_PER_MONTH` (200) per org; `GET …/projects/{id}/render`, `GET …/content/renders/{id}` (short-lived output URL when done), `POST …/renders/{id}/cancel`. The job spec is frozen at queue time and holds storage keys only.
- Worker API (`Authorization: Worker <token>`, user tokens are not accepted): `POST /api/v2/workers/claim` (SKIP LOCKED on Postgres) returns the spec, presigned GETs for that job's inputs and one presigned PUT for `content/<org>/renders/<job>/output.mp4`; `…/jobs/{id}/heartbeat|complete|fail` only for the worker holding the job. Completion is validated (resolution matches the preset, codec h264/hevc/av1, duration within limits, plausible GPU seconds, output present) before it counts. Stale jobs (`RENDER_STALE_SECONDS`, 600) are requeued; a cancelled job answers 404 to its worker.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 9a — Content Studio basics (local)

- New `content_studio` app: `BrandKit`, `ContentTemplate`, `MediaAsset`, `ContentProject` (`content_studio/0001_initial`). Flag `content_studio` (501 when off).
- Brand kits and templates: everyone with `content.use` reads them; `content.manage` (admin) edits. The FLOQ question card (1920x1080, 3 s, two plates dissolving, left headline in Inter Display Medium, blur-to-sharp per line, only the question changes) is seeded per org on first read.
- Assets: `POST …/content/assets` returns a presigned PUT for that asset's own server-built key (`content/<org>/<asset>/…`), only for allowed media types and sizes (`CONTENT_MAX_UPLOAD_MB`). `…/complete` needs the object in storage (no larger than declared) and caps length (`CONTENT_MAX_SOURCE_SECONDS`). Storage is `CONTENT_STORAGE=s3|local`; unset → 501.
- Projects: members see and edit their own; owners, admins and team leads see all. Sources must be ready assets the user can see.
- New keys: `content.use` (member), `content.manage`, `content.publish`, `content.approve`, `social.connect`, `consent.manage` (admin; grantable). V1 behaviour: unchanged. Not pushed.

## Phase 8 review fixes (local)

- Independent review; no critical or high findings; fourteen medium/low findings fixed (`REVIEW_PHASE_8.md`): no emails in reports or proposal summaries, report hours limited to the team's tasks, agent events limited to what the creator can see with an hourly cap, tool switch honoured at approve, project access on task create, cron floor across midnight, run-now throttle, audit of proposals/denials/reports, hash-pinned share approval, reviewer room ids filtered, skills for active members only.
- New settings `AGENT_MAX_RUNS_PER_HOUR` (12). Share approval now requires the `hash` from the share request. Not pushed.

## Phase 8f — scheduled and triggered agents (local)

- New `agents` app: `AgentSchedule`, `AgentRun` (`agents/0001_initial`). Flags `scheduled_agents` and `buddies` (501 when off).
- `GET/POST /orgs/{org}/agents/schedules`, `PATCH/DELETE …/{id}`, `GET …/{id}/runs`, `POST …/{id}/run`. A member schedules a buddy they can use: five-field UTC cron (at most every 15 minutes, checked over the next day) or an event (`task.overdue`, `member.joined`, `meeting.ended`). At most 20 per person. Others see nothing; admins can list and pause, not rewrite.
- `manage.py tick_agents` (every minute) queues due cron runs and overdue-task events; `member.joined` and `meeting.ended` come from signals. Each event runs once per schedule (unique key). Runs go on the 7g worker (`agents.run`); without a worker the run is recorded as skipped.
- A run is one buddy turn as the **creator, now**: inactive creator or a buddy they can no longer see pauses the schedule; write tools become proposals the creator approves. Event context is ids only, quoted as data. Every run keeps its thread and trace.
- V1 behaviour: unchanged. No AWS change; the production scheduler is an `INFRA_CHANGES.md` item. Not pushed.

## Phase 8e — skills and assignment suggestions (local)

- `organizations.SkillTag` and `MemberSkill` (`organizations/0003_skills`). `GET/POST /orgs/{org}/members/{user}/skills`, `DELETE …/skills/{id}`. A member adds their own skills (unconfirmed). A lead of one of the member's teams, or an admin, adds confirmed ones and can remove any. Names are case-insensitive per org. Audited.
- `GET /orgs/{org}/tasks/{task}/suggest-assignee` (flag `assign_suggestions`, default off). Deterministic score: matched skills (confirmed count more), done tasks in the team, minus open tasks. Only people the requester may assign are listed (a member sees only themselves; a lead sees their team). Email only with `org.members.view_contact`. Nothing is assigned.
- V1 behaviour: unchanged. Not pushed.

## Phase 8c/8d — approved actions and team reports (local)

- New `actions` app: `ToolDefinition` (synced from `actions/registry.py` by `actions/0002_sync_tools`), `ActionProposal` (24 h expiry), `EmailDraft`, `AutoReport`.
- Tools: `tasks.create`, `tasks.assign`, `tasks.update_status`, `rooms.post_message`, `meetings.create`, `email.draft` (stored, never sent), `reports.generate`. The `direct` client sends OpenAI-style `tools` and reads `tool_calls`.
- Flag `ai_actions` (default off). A buddy offers only the tools in its list that are enabled and that the user holds **now**. A tool call becomes a proposal only after strict schema validation (no unknown fields) and a target check for that user (room access, task visibility, assignment rules, team in org). Nothing runs at propose time.
- `GET /orgs/{org}/actions?status=`, `POST …/actions/{id}/approve` (optional edited `arguments`, validated again) and `…/reject`. Only the person the proposal was made for decides. On approve, the target is re-checked for the approver now; if access was lost, nothing runs and the proposal stays open. The proposal row is locked, so it runs at most once. Results go to `AuditEvent`, an `AITrace` span and a "Done:" line in the thread.
- Flag `auto_reports` (default off). `GET /orgs/{org}/teams/{team}/reports`, `POST …/reports/generate` (`daily_standup` or `weekly_report`), `POST …/reports/{id}/post` (once, to the team room). Team lead or admin only. The draft is built from rows (done, in progress, blocked, overdue, time by member, room activity) and cites every task and time entry id. No model call.
- Fix: `POST /tasks` accepted a `project` id from another org. Task creation now goes through `tasks.services.create_task`, which checks the team and project belong to the org and are writable (404 otherwise). A malformed id is 404, not 500.
- New key `report.generate` (team). V1 behaviour: unchanged. Not pushed.

## Phase 8b — Buddy Builder and sharing (local)

- `POST /orgs/{org}/buddies` (`buddy.create`, member default) makes a **private** buddy. `GET/PATCH/DELETE …/buddies/{id}` for its creator, or `buddy.manage` (admin) for any buddy and the only way to edit built-ins. Others get 404, or 403 when they can see but not edit it.
- Sources and tools are checked against the **editor's** access when saved: rooms must be readable by them now; tools need the tool's permission (`reports.generate` needs a lead or admin). The prompt is at most 4000 characters, with at most 10 presets.
- `POST …/buddies/{id}/share` with `team`, `org` or `private`. A team share needs that team's lead (or admin); an org share needs `buddy.manage`. A lead sharing with their own team, or an admin, is approved at once. `GET …/buddies/share-requests` lists what you can decide; `POST …/share/approve|reject`. A pending or rejected share is visible to the creator only.
- Changing the prompt, sources, tools or model of a shared buddy sends it back to `pending` (hidden from others until re-approved). A rename does not. Every change writes an audit event (field names only).
- New module `actions/registry.py` lists the tools (used fully in 8c). V1 behaviour: unchanged. Not pushed.

## Phase 8a — buddies and buddy threads (local)

- New `buddies` app: `Buddy` (spec 6.10) and `BuddyPin`; `brain.Chat.buddy` nullable FK. V1 chat views now also filter `buddy IS NULL`, so buddy threads are reachable only through `/api/v2/`.
- `GET /orgs/{org}/buddies`, `PUT …/buddies/pins`, `GET/POST …/buddies/{buddy}/threads`, `GET …/buddies/threads/{id}`, `POST …/send`. Flag `buddies` off → 501. A buddy is visible to its creator; team and org buddies only once their share is approved; built-ins to everyone. A thread closes (404) when its buddy is no longer visible.
- Sends go through `direct` only (platform key or the user's BYOK key; 501 without `direct`, never the legacy host). Retrieval reuses 7i with the **viewer's** live access narrowed by the buddy's `allowed_sources`; a shared buddy never gives the creator's rooms. Usage `surface=buddy`.
- Nine built-in buddies seeded into the FloLabs org only (`buddies/0002_seed_buddies`, slug from `BUDDY_SEED_ORG_SLUGS`, default `flolabs`; reversible). `manage.py seed_buddies --org <slug>` for another org. New keys `buddy.create` (member) and `buddy.manage` (admin) for 8b.
- V1 behaviour: chat list and detail exclude buddy threads (there were none before). No AWS change. Not pushed.

## Phase 7 review fixes (local)

- Independent review of 7h–7k and the room-access fix; six findings, all fixed (`REVIEW_PHASE_7.md`). Team and project rooms now also require live team/project membership. Knowledge chunks carry the source version and are dropped when stale. Cached translations carry the message version. Shared source quoting. BYOK date and provider-error handling.
- Migration `knowledge/0003_chunk_source_version`. V1 behaviour: unchanged. Not pushed.

## Phase 7k — BYOK (local)

- New `ai_credentials` table (`integrations/0002_credential`). Secrets are AES-256-GCM ciphertext under `CREDENTIALS_ENCRYPTION_KEY` (64 hex, never the all-zero key), bound to the credential id and org id. Only `last4` is ever returned.
- `GET/POST /api/v2/orgs/{org}/credentials`, `PATCH/DELETE …/credentials/{id}`. Flag `byok` off → 501. No encryption key → 501 `not_configured`. Personal keys: only the owner sees, uses, edits or deletes them; everyone else (owner and admin included) gets 404. Org keys: `credential.manage` (owner, admin) only; members get 403 on writes and do not see them.
- A new or rotated key is `pending` until `GET {base}/v1/models` answers (20 s timeout): 2xx `active`; 401/403/other 4xx `rejected`; 429, 5xx, redirects, timeouts `indeterminate`. `expires_at` in the past → `expired`. Disable and enable (re-check) through PATCH. Writes go to the audit log without the secret.
- Keys are sent only over HTTPS to hosts in `BYOK_ALLOWED_HOSTS`, with no userinfo, port or path tricks, and redirects are never followed (no SSRF, no header leak).
- Room AI send accepts `credential_id` and `model`. The call goes through `direct` with that key, is recorded as `credential_source=customer`, and is not counted against the platform budget. A key that is not active → 409. A failed call → error. Never a fallback to the platform key or the legacy host. `GET /ai/models` lists the keys the user can use under `providers`.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7j — live translation (local)

- `GET …/rooms/{room}/messages?translate_to=<code>`: flag `live_translation` off → 501 as before. On without a `direct` provider → 501 `not_configured`, no network, never the legacy multimodal host.
- On and configured: each uncached message on the page is translated by its own `direct` call (a message cannot steer another message's cached translation). The system prompt says the text is content, not instructions. At most `TRANSLATION_MAX_PER_REQUEST` (20) calls per request; the rest come back with `translation_error: "deferred"`. The platform budget is checked first. The AI send throttle applies.
- The stored body never changes. Translations are cached per message and language and redone after an edit. Each call writes `UsageEvent(operation=translate)` and `AITrace(surface=translation)`.
- The old stub that would have cached `[ar] <body>` is gone. V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7i — knowledge ask, retrieval before ranking (local)

- New `knowledge_chunks` table (`knowledge/0002_chunks`): org, room, source type and id, chunk text, content hash, model and dimension. Vectors stay in the 7h store under the chunk id.
- Saving a document or a room message queues `knowledge.index` on the 7g worker when the org's `memory_search` flag is on. Unchanged text is not embedded again. Deleting a source, soft-deleting a message, or deleting a room removes its chunks and vectors at once, whatever the flag says.
- `manage.py index_knowledge --org <id> [--inline]` backfills existing docs and messages. It refuses when the flag is off or no worker runs (use `--inline`).
- `POST /api/v2/orgs/{org}/knowledge/ask`: permission `knowledge.ask` (member default) plus `search.use`. Flag off → 501 `not_implemented`, no embedder call. No `direct` provider → 501 `not_configured`, never the legacy multimodal host. The asker's **current** rooms (`accessible_rooms`, E37) and `docs.view` decide which chunks are ranked; nothing else is scored. A hit whose source is gone is dropped. Retrieved text is quoted inside `<source>` tags and the system prompt says it is data, not instructions. Returns the answer, citations and usage (`surface=knowledge_ask`). No readable match → no provider call.
- pgvector search takes the allowed set as a SQL subquery and sets `hnsw.iterative_scan` when the server supports it (pgvector 0.8+).
- Fix: `memory/context_assembler.py` passed the node object to `retrieve_from_cold_storage`; it now passes `metadata.vault_uri` and falls back to `metadata.raw_text`.
- V1 behaviour: unchanged except the assembler fix (tier-3 nodes with a `vault_uri` are now actually read; none exist today, Q4). No AWS change. Not pushed.

## Room access follows team and project membership (local)

- Leaving a team or a project removes the user from that room (signals plus pruning). Owners and admins keep team, project and org rooms, but no longer read direct or group rooms they are not in (E37, Q40). Room list, room search, global search, docs search and announcements use one helper, `accessible_rooms`.

## Phase 7h — vector store and embeddings client (local)

- New `knowledge` app. `get_embedder()` returns an OpenAI-compatible `/v1/embeddings` client (`EMBEDDINGS_BACKEND=http`, HTTPS only, model and dimension from config), a fake embedder in tests, or None ("Not configured", no network). A vector of the wrong length is rejected and never stored.
- `get_store()` returns pgvector (`knowledge_vec_1024`, HNSW m=16, ef_construction=64) when the extension is installed, a JSON store for local dev and tests (`KNOWLEDGE_VECTOR_STORE=json`), or None. `search()` ranks only chunk ids the caller already authorized.
- Migration `knowledge/0001_pgvector` checks `pg_available_extensions` first and never aborts when the extension is missing or cannot be created. SQLite skips it.
- Nothing is indexed yet and no flag is on. V1 behaviour: unchanged. No AWS change. Not pushed.

## Review fixes for 7b, 7d, 7f (local)

- Pricing uses both input and output prices; a total without a split uses the higher price. Usage rows record the provider name, so `PriceTable` lookups match. Missing tokens are estimated from the full prompt and the reply.
- `PUT /budgets` validates the amount and currency (400 instead of 500).
- Room thread send rejects text over `AI_MAX_INPUT_CHARS` before calling the provider, and sends at most `AI_THREAD_HISTORY_MESSAGES` messages of history.
- `direct` requires HTTPS for remote hosts. `http://` is allowed only for localhost.
- See `REVIEW_7D_7G.md`. V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7g — PostgreSQL job worker (local)

- `jobs_queue` table and `manage.py run_jobs`. The claim is a short committed transaction (`SELECT ... FOR UPDATE SKIP LOCKED` on Postgres, a conditional update elsewhere). The handler runs outside any transaction, then the row becomes done, retried with capped backoff, or failed after 5 attempts. Crashed rows are requeued after `JOBS_STALE_SECONDS`.
- `run_jobs` polls until SIGTERM/SIGINT. `--once`, `--max-jobs`, `--max-seconds` and `--exit-when-idle` stop it earlier. Under tests it can never loop without limits.
- `enqueue` without a worker (`JOBS_WORKER_ENABLED=False`, the default) creates no row and returns `unavailable`.
- A real two-connection test proves a locked row is skipped (Postgres only).
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Auth fix: tokens in the same second as a password change (local)

- New tokens carry `iat_ms`. A token minted right after first-login or a reset was rejected when it shared the second of `password_changed_at`. Tokens without `iat_ms` are compared at the start of their second, so a pre-change token from that second is still rejected.
- Restored `public/fonts/fa-solid-600.eot`, which the 7g WIP commit had removed.
- V1 behaviour: V1 tokens gain an extra `iat_ms` claim; V1 response shapes are unchanged.

## Phase 7f — PriceTable and platform budgets (local)

- Budget unit is money from a versioned `PriceTable`. Flag `budgets` default off is 501. Members cannot view or manage. A platform call over the cap is 429 when the flag is on. Customer/BYOK calls are not capped. Missing token counts are estimated and stored with `estimated=true`, never as a measured 0.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7e — usage read (local)

- `GET /api/v2/orgs/{org}/usage`: a member sees only their own rows; owner and admin see the org. Null tokens are `null` with `token_state: unknown`. `estimated=true` is labelled. Outsider and inactive members get 403. No secrets.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7d — room AI threads (local)

- Room threads are private to the asking user. Another member of the same room, and an owner or admin, get 404 on list, read, and send. Flag `room_ai` off is 501. Send is throttled per user. The prompt is the user's own thread only; room messages are not included. Echo replies are not stored. V1 chat list hides room threads.
- V1 behaviour: V1 chat list still only shows personal chats (`room IS NULL`). No AWS change. Not pushed.

## Hang-safe tests (local)

- Django tests now dump every thread stack and exit after 20 minutes (`TEST_HANG_TIMEOUT`). Outbound sockets other than localhost raise immediately, so a missed mock cannot wait on the multimodal host.
- Cause of the 7d hang: thread send tests called the real adapter (`urlopen` to `35.153.90.219`) when a patch missed; `MULTIMODAL_SERVICE_TIMEOUT` was 60s and several waits looked like a frozen suite. Tests now mock `get_provider()`, and the runner blocks that host.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7c — model list (local)

- `GET /api/v2/orgs/{org}/ai/models` returns platform models from the registry and an empty provider list until personal keys exist. An outsider or inactive member gets 403. The body has no key material.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7b — direct chat client (local)

- `direct` is an OpenAI-compatible chat-completions client. The model must be on the config allowlist. Token counts come from the response. 4xx is not retried. A self-hosted base URL is the same client. Missing config does not open a socket. Tests mock HTTP.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 7a — provider interface (local)

- `AI_PROVIDER_BACKEND` defaults to `multimodal_legacy`. The V2 provider treats the HTTP 200 echo body as `provider_error` and does not return it as the reply. A response with no token fields is stored as NULL by the V2 writer. The `direct` backend is a stub that does not open a socket.
- V1 `POST /api/brain/chats/<id>/send/` still returns 200 with `usage.total_tokens` as an integer (0 when the service omits the field). The V1 telemetry writer still stores that integer.
- Tests: 111 on SQLite and 111 on Postgres 5433 (`--noinput`). No AWS change. Not pushed.

## Rollout decisions (local docs)

- Q11, Q12, Q28, Q29, Q31, Q3, and Q39 are decided. Q12: a failed S3 write does not leave tier-3 ciphertext, so the first V2 deploy sets a new `AES_MASTER_KEY`. The other listed product and media questions stay open as configurable defaults until the named owner confirms them.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Multimodal contract and Phase 7 plan (local docs)

- Closed Q1 from `multi-modal-perception` `main` at `1d875b8` (the EC2 host may differ) and Q31 (production `SECRET_KEY` is 66 characters). Proposal for the multimodal team is `MULTIMODAL_CONTRACT_PROPOSAL.md`. Phase 7 is planned in `PHASE_7_PLAN.md` and not started.
- V1 behaviour: unchanged in this commit. No AWS change. Not pushed.

## Health check Mongo timeout (local)

- `GET /api/dashboard/health/` still returns the same JSON shape. A missing MongoDB now fails in about 2 seconds (`MONGO_TIMEOUT_MS`, default 2000) instead of pymongo's 30 second selection timeout, and the body stays `status: degraded` with `mongodb: disconnected`.
- V1 behaviour: faster degraded answer, same fields. No AWS change. Not pushed.

## Infra ground truth (local docs, 2026-10-20)

- Recorded the read-only AWS audit in `AUDIT.md`: image date, env names, no Redis/SQS/Mongo/staging, pgvector on PostgreSQL 15.17, and the multimodal host's shape. No account IDs and no secret values.
- Production does not migrate on container start (`Dockerfile` `CMD` is `runserver`; the task definition sets no command). The Dockerfile was not changed.
- Deploy checklist in `RUNBOOK.md` and `INFRA_CHANGES.md`. `AES_MASTER_KEY` and `CORS_ALLOWED_ORIGINS` are the two settings that break a production boot of this branch.
- Tests: `ProductionEnvBootTests` (the 12 production env names). Stage B 501 and empty join URL were already asserted by `RoomApiTests.test_translation_keeps_original`, `MeetingApiTests.test_member_cannot_manage_and_confirm_required`, and `Phase46QualityTests.test_recordings_and_transcripts_isolated`. `test_voice_video_defaults_off_and_join_url_stays_empty` covers the `voice_video` default. Meeting create no longer evaluates `meeting.id` before the row exists.
- Provider layer and pgvector stay in Phase 7 (`AI_PROVIDER_BACKEND` default `multimodal_legacy`). Not implemented here.
- V1 behaviour: unchanged. No AWS change. Not pushed.

- Authorization: every V2 endpoint in this stage goes through `can()`. Missing permission is 403. An in-org object outside room or team scope is 404. Denial tests cover announcements, recordings, transcripts, files, message edits, and room members.
- Unimplemented work returns 501 or stays behind a flag that defaults off. No stub translation, transcript, summary, or `meet.local` join URL. Undefined impact score shows "Not configured".
- Project rooms sync from project membership. Files are room-scoped. Postgres search uses full text, with an `icontains` fallback on SQLite. Chat follows cursor pages.
- Playwright smokes: sign in, workspace switch, a room message, tasks, Flo Chronos start/stop, and Mission Control denial for a member.
- `public/fonts/fa-solid-600.eot` was restored in the working tree. It was not deleted in a commit. No other asset is deleted versus `origin/main`.
- V1 behaviour: unchanged. No AWS change. Not pushed.

## Phase 6: Docs, files, tools, search

- `docs` app: room documents with optimistic locking (409 on stale `version`), revision cap, local file presign/complete (no S3/AWS).
- `integrations` app: `ExternalTool` rail with Figma/Canva/Cursor/Notion/Discord/GitHub defaults. Members list; `tools.manage` creates/edits/deletes.
- `GET /orgs/{org}/search` is permission-filtered (rooms, tasks, docs, meetings the caller can see).
- Frontend: docs tab, tools rail + `/tools`, `/search`.
- V1 behaviour: unchanged.

## Phase 5: Meetings

- `meetings` app: create/list meetings on a room, recordings (10 per page), transcribe/summarize jobs (eager local stubs), summary + action-item → task only with `confirm: true`.
- Join URLs are `https://meet.local/{id}`. No cloud meeting provider.
- Frontend: `/w/[org]/rooms/[roomId]/meetings`.
- V1 behaviour: unchanged.

## Phase 4: Rooms, chat, notifications

- `rooms` app: team rooms (unique per team), project/direct unique constraints, messages, per-reader translation cache (`[lang] {body}`), announcements.
- Team membership signals keep the team room in sync. Owners/admins can open any org room; members only rooms they belong to.
- `notifications` app: list own notifications, mark read.
- `POST /api/v2/realtime/ticket` returns 503 unless the `realtime` flag is on (Q7 off).
- Frontend: rooms sidebar, room chat with 5s polling, translation toggle, Decision 13 timestamps, `/notifications`.
- V1 behaviour: unchanged.

## Mission Control and access settings

- Mission Control returns team metrics, top accomplishments, blockers with duration, upcoming deadlines with priority, and per-member workload with `task_ids` for drill-down. `mission.view` is lead/admin only (member 403).
- Settings/access lists pending permission requests and active grants (approve/reject/revoke).
- V1 behaviour: unchanged.

## Quality pass Phases 0–3 (local, before Phase 4)

- Team/project scoped keys now require membership unless owner/admin. Team A cannot read Team B members, tasks, time entries, or team reports (404).
- Members assign only themselves (403). Leads assign only inside their team (404). Inactive members cannot sign in, be assigned, or receive new DMs.
- Second timer start is 409; GET `/timer` returns the same running entry on a new client. Weekly report `?period=week` equals the sum of that week's entries. Bad HR HMAC is 401; pending sign-in is 403.
- Frontend screens for directory, member profile, Kanban + assign panel, API timer, weekly reports, and calendar, each with loading/empty/no-access/error.
- V1 behaviour: unchanged.

## Phase 3: Time tracking

- New `timetracking` app: tags, time entries, one open timer per user.
- Timer start/stop, entries, me/team reports, dashboard, calendar of task due dates.
- Frontend `/w/[org]/time` with a top-bar timer control.
- V1 behaviour: unchanged.

## Phase 2: Tasks

- New `tasks` app: Task, assignment, activity, project templates.
- Members create tasks and assign only themselves; owner/admin/team lead can assign others (Decision 2). Statuses `to_do` / `in_progress` / `done`; `is_blocked` is a flag.
- `GET /orgs/{org}/mission-control` aggregates. Frontend Kanban shell and `/w/[org]/tasks`.
- V1 behaviour: unchanged.

## Phase 1: Organization and member lifecycle (same local branch)

- `GET/POST /orgs/{org}/members`, `PATCH .../members/{user}`: invite attaches to an existing `users` row (Q34); pending hidden from the directory; email/phone only with `org.members.view_contact` (Q33).
- Deactivate/pause/terminate bumps `password_changed_at` so V2 tokens issued earlier stop working.
- Teams and projects list/create/patch.
- HMAC HR webhook `POST /api/v2/integrations/hr/applicants` (`HR_WEBHOOK_SECRET`). Unconfigured → 503.
- Frontend shells: `/w/[org]/directory`, `members/[userId]`, `mission-control`, `settings/access`.
- V1 behaviour: unchanged.

## Phase 0: Foundation and hardening (branch `v2/phase-0-foundation`)

### PR 0f: Staging docs and disabled CD

- `docs/v2/INFRA_CHANGES.md`, `RUNBOOK.md`, `TECH_DEBT.md`.
- `.github/workflows/backend-deploy.yml` present with `if: false` (no AWS calls).
- No production or AWS change.

### PR 0e: Frontend V2 shell

- `/w/[orgSlug]` cockpit shell (icon rail, rooms, top bar, right rail) with empty states.
- V2 auth screens at `/w/signin`, `/w/first-login`, `/w/reset-password`. V1 `/signin` untouched.
- F8: `NEXT_PUBLIC_API_URL` has no `api.flobrain.ai` fallback; dev uses `http://127.0.0.1:8000`; production builds fail if unset.
- V2 client, WorkspaceGuard, tokens, states, i18n message catalogs (en/ar), Playwright skeleton, website-ci unit + Playwright jobs.
- V1 behaviour: marketing chrome hidden only under `/w/*`.

### PR 0d: Telemetry and best-effort V1 writes

- New `telemetry` app: `UsageEvent`, `AITrace`, `ProductEvent`, `FeedbackItem`.
- V1 chat send writes usage + `surface=v1_chat` traces best-effort (E28); a telemetry failure cannot change the V1 200 body.
- `generate_v2()` swallows adapter exceptions; V1 `generate()` keeps its existing error handling. `model` is forwarded as a multipart field when given (Q1).
- `jobs.enqueue` runs eager in DEBUG/tests; non-DEBUG without a broker returns `unavailable`.
- V2 `POST /orgs/{org}/events` (allowlisted names/properties), `POST /orgs/{org}/feedback`, admin list endpoints.
- V1 behaviour: send response shape unchanged.

### PR 0c: Organizations, permissions, V2 auth

- New `organizations` app: Organization, memberships, teams, projects, grants, permission requests, append-only audit events.
- `can()` engine with Phase 0 permission matrix; platform admin bypass; inactive members denied.
- Additive user profile fields and `PasswordResetToken` (`users.0003`). New tokens include `jti` (old tokens stay valid).
- V2 auth under `/api/v2/`: signin, refresh, signout (Bearer required), forgot/reset password, first-login, `GET /me`.
- `BearerJWTAuthentication` rejects tokens issued before `password_changed_at`. OpenAPI Bearer scheme declared.
- `FLOBRAIN_V2` settings dict, `FRONTEND_BASE_URL`, `DRF_NUM_PROXIES`, `CREDENTIALS_ENCRYPTION_KEY` read (unused until Phase 7).
- `seed_v2_demo` refuses to run when `DEBUG=False`.
- V1 behaviour: unchanged paths and response shapes. `get_user_from_request` moved to `jwt_utils` and re-exported from views.

### PR 0b: P0 hardening

- `users.User.is_platform_admin` (additive migration `0002`). Set only via Django admin or `manage.py set_platform_admin`.
- Model registry writes require `is_platform_admin` (403). Reads unchanged.
- Memory node GET/PATCH scoped to `owner_id = str(user.id)` (404 outside scope). Platform admins see all nodes, including `system`. PATCH validated (`name`, `memory_type`, `relevance`). Save still ignores client `owner_id` unless platform admin.
- CORS allowlist via `CORS_ALLOWED_ORIGINS` (localhost defaults). `CORS_ALLOW_ALL=True` remains an escape hatch.
- `GET /healthz` returns 200 before host validation.
- Startup check refuses a missing/zero `AES_MASTER_KEY` in non-DEBUG unless `ALLOW_INSECURE_AES_MASTER_KEY=1` (Q12 still open). Short `SECRET_KEY` is a warning.
- `/api/dashboard/error-logs/` returns both `"error-logs"` and `"error_logs"` (Q38).
- V1 behaviour: CORS is narrower by default (localhost still works). Memory node detail/PATCH no longer leak other users' nodes. Model registry writes now 403 for ordinary users. Error-logs response adds a second key; the original `"error_logs"` key from #250 stays.

### PR 0a: Django backend CI and safe test discovery

- Added `.github/workflows/django-backend-ci.yml`: Python 3.11 + Postgres 15; runs `check`, `makemigrations --check --dry-run`, `migrate`, the full test suite, and OpenAPI schema generation on every push and PR to `main` that touches `flobrain-core/backend/`. The existing "Backend CI" workflow still only covers `flobrain-cloud/`.
- Moved five manual scripts that run against live MongoDB/FAISS when imported out of Django's test discovery: `memory/test_crud.py`, `test_mongo.py`, `test_embeddings.py`, `test_hybrid_retrieval.py`, `test_knowledge_graph.py` → `memory/manual_checks/` (`crud.py`, `mongo_workflow.py`, `embeddings.py`, `hybrid_retrieval.py`, `knowledge_graph.py`). Contents unchanged.
- Fixed the test fixture in `memory/tests.py` to create nodes owned by the test user. `main` was red after PR #250 scoped the memory graph to the caller.
- V1 behaviour: no change.
