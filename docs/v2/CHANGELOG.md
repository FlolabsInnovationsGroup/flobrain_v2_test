# FloBrain V2 Changelog

Newest first. Each entry names the PR, what changed, and any V1 behaviour change.

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
