# FloBrain V2: Build Plan

Status: Phases 0–6 are built on local branch `v2/phase-0-foundation` (2026-10-20). Stage B review is closed. Phase 7 is not started.

Reads with: `AUDIT.md` (what exists), `DECISIONS.md` (spec decisions 1 to 51, engineering decisions E1 to E36), `OPEN_QUESTIONS.md` (Q1 to Q39), `PHASE_7_PLAN.md` (the Phase 7 split).

Paths: backend files are relative to `flobrain-core/backend/`, frontend files to `flobrain-website/`, unless they start with the repo root.

---

## 0. Ground rules for every phase

- One branch per phase from `main` (`v2/phase-<n>-<slug>`), one PR to `main` (Decision E2). Large phases are split into **stacked PRs inside the phase** (0a, 0b, ...) so each diff stays reviewable; the phase's Definition of Done (spec Section 13) is checked on the last one.
- V1 paths and shapes do not change, except the deliberate P0 fixes in Phase 0 (D2 remainder, D3, D4), each listed in `docs/v2/CHANGELOG.md`.
- New V2 code: DRF serializers, `@extend_schema`, explicit permission classes, `V2APIView` base (Decision E4), tests for allowed and denied paths.
- Migrations are additive and reversible. A migration list per phase is below; names are indicative, numbering follows the app's last migration.
- Infra needs go into `docs/v2/INFRA_CHANGES.md` and are not applied.
- Blocking open questions are named per phase. A phase starts only when the previous phase is Done.

### Current migration heads (verified)

| App | Last migration |
|---|---|
| `users` | `0001_initial` |
| `brain` | `0002_message_token_fields` |
| `memory` | `0001_initial` |
| `model_registry` | `0001_initial` |

---

## Phase 0: Foundation and hardening

Blocking questions: none for the code. Q11, Q12, Q27, Q28 block the **production rollout**, not the PRs.

### PR 0a: Make the backend testable in CI (no behaviour change)

| File | Change |
|---|---|
| `memory/test_crud.py`, `test_mongo.py`, `test_embeddings.py`, `test_hybrid_retrieval.py`, `test_knowledge_graph.py` | Move to `memory/manual_checks/` without the `test_` prefix (Decision E15) |
| `memory/tests.py` | Test fixture nodes created with `owner_id=str(self.user.id)`. `main` is red since PR #250 scoped the graph to the caller without updating this fixture (1 failing test); this aligns the test with already-merged behaviour |
| repo root `.github/workflows/django-backend-ci.yml` (new) | Python 3.11, Postgres 15 service, `pip install -r requirements.txt`, `check`, `makemigrations --check --dry-run`, `test` (full discovery), schema generation smoke test; triggered on `flobrain-core/backend/**` and the workflow file |

Dropped from the Discovery draft of 0a, to keep it minimal: `requirements-dev.txt` and `flobrain/settings_test.py` (CI configures the existing settings through env vars). The `/api/v2/`-only `--fail-on-warn` schema check moves to PR 0c, when the first V2 view exists.

Acceptance: the workflow passes on `main`'s code plus this PR (22 tests).

### PR 0b: P0 security fixes for V1

| Defect | Files | Change |
|---|---|---|
| D4 CORS | `flobrain/settings.py` | `CORS_ALLOWED_ORIGINS` from env (comma list); default includes `http://localhost:3000`, `http://127.0.0.1:3000`; `CORS_ALLOW_ALL_ORIGINS` only if env `CORS_ALLOW_ALL=True` (escape hatch for the rollout, documented in INFRA_CHANGES) |
| D2 memory isolation | `memory/views.py`, `memory/serializers.py` (new) | Graph, memory activity and save were already scoped by PR #250. 0b adds: node detail and node PATCH scoped to `owner_id = str(user.id)` (outside scope → 404); PATCH validated by a serializer (B4); `is_platform_admin` sees all nodes in graph and detail (E12) |
| D3 registry writes | `model_registry/permissions.py` (new), `model_registry/views.py` | POST/PATCH/DELETE require `user.is_platform_admin` → 403; reads unchanged (E13) |
| D10 mocks | none | Already done by PR #250 (E14 superseded) |
| Q38 error-logs key | `dashboard/views.py`, `dashboard/tests.py` (new) | Response carries both `"error-logs"` (V1 frontend) and `"error_logs"` with the same list, for a deprecation period |
| D5 key check | `flobrain/checks.py` (new), `flobrain/apps.py` or `users/apps.py` | Startup check: non-DEBUG + missing/zero `AES_MASTER_KEY` → error unless `ALLOW_INSECURE_AES_MASTER_KEY=1` (E21); `SECRET_KEY` < 32 bytes → warning (Q31) |
| Health | `flobrain/middleware.py` (new), `flobrain/settings.py` | `HealthCheckMiddleware` before `CommonMiddleware`, answers `GET /healthz` 200 (E18) |
| Tests | `memory/tests.py`, `model_registry/tests.py`, `dashboard/tests.py` (new) | Update the ~7 tests that assumed open access; add isolation and 403 tests |

`users.User` needs `is_platform_admin` for D2/D3, so PR 0b includes migration `users/0002_user_is_platform_admin`.

### PR 0c: Organizations, permissions, audit, V2 auth

New app `organizations/`:

| File | Contents |
|---|---|
| `models.py` | `Organization`, `OrgMembership`, `Team`, `TeamMembership`, `Project`, `ProjectMembership` (E8), `PermissionGrant`, `PermissionRequest`, `AuditEvent` (append-only: `save()` refuses updates, no delete in code; admin read-only) |
| `permissions/registry.py` | Every permission key with its matrix row and per-role default (E6); keys used in Phase 0: `org.members.view`, `org.members.view_contact`, `grants.create`, `grants.revoke`, `permission_requests.create`, `permission_requests.decide`, `audit.view` |
| `permissions/engine.py` | `can(user, perm_key, obj=None)`: org role → team/project scope → active grants; inactive membership → False |
| `permissions/drf.py` | `IsActiveOrgMember`, `HasPerm("key")`, object-scope helper returning 404 outside scope |
| `services.py` | `sync_user_type(user)` (E9), `audit(actor, action, target, payload, request)` |
| `flags.py` | Effective flag = org flag AND membership flag (entitlements added in Phase 17) |
| `serializers.py`, `views.py`, `urls.py` | Org, grants, permission requests, audit events |
| `tests/test_matrix.py` | Parametrized test per implemented key × role, allowed and denied |
| `management/commands/seed_v2_demo.py` | FloLabs org, 3 teams, leads, members (refuses to run when `DEBUG=False`) |

Additions to existing apps:

| File | Change |
|---|---|
| `users/models.py` | `is_authenticated`/`is_anonymous` properties (E5); fields from spec 6.2: `user_type`, `phone`, `avatar_url`, `discord_handle`, `linkedin_url`, `about_me`, `must_change_password`, `temp_password_expires_at`, `password_changed_at`, `timezone`, `locale`, `portfolio_slug`; `PasswordResetToken` |
| `users/authentication.py` (new) | `BearerJWTAuthentication` wrapping `jwt_utils`; rejects tokens with `iat < password_changed_at`; drf-spectacular `OpenApiAuthenticationExtension` declaring a Bearer scheme (fixes B12 for V2) |
| `users/jwt_utils.py` | Add `jti` to new tokens (old tokens without `jti` stay valid for V1) |
| `users/middleware.py` (new) | Throttled `last_active` update (at most once per minute) for V2 requests |
| `users/v2/views.py`, `users/v2/serializers.py`, `users/v2/urls.py` (new) | V2 auth endpoints below; passwords checked with `validate_password` (B8); reset email via existing SMTP settings and `FRONTEND_BASE_URL` |
| `core_v2/` (new package, not an app with models) | `V2APIView`, exception handler, pagination, cursor pagination, idempotency helper, throttles (E4, E10, E19) |
| `flobrain/urls.py` | `path("api/v2/", include("flobrain.urls_v2"))` |
| `flobrain/urls_v2.py` (new) | Mounts V2 URLconfs |
| `flobrain/settings.py` | `FLOBRAIN_V2` dict (E11), `DRF_NUM_PROXIES`, `FRONTEND_BASE_URL`, `CREDENTIALS_ENCRYPTION_KEY` read (used in Phase 7) |

### PR 0d: AI telemetry foundation and jobs

| File | Change |
|---|---|
| `telemetry/` (new app) | `UsageEvent`, `AITrace` (spec 6.9), `ProductEvent`, `FeedbackItem` (spec 6.19) |
| `brain/llm/multimodal_adapter.py` | Send `model` as an extra multipart field when given (Q1 default); catch all exceptions (B2) **only in a new V2 entry point** `generate_v2()`; V1 `generate()` keeps its behaviour |
| `brain/views.py` | V1 send also writes `UsageEvent` + `AITrace` (`surface=v1_chat`), **best-effort** (E28): wrapped so any failure is logged and never changes the V1 response body or status |
| `brain/tests.py` (new) | Test: V1 send returns 200 with the unchanged response shape when the telemetry write raises |
| `jobs/` (new package) | `enqueue(name, payload)`, registry, eager executor (E17) |
| `telemetry/views.py` | `POST /orgs/{org}/events` (allowlisted properties), `POST /orgs/{org}/feedback`, admin list endpoints |

### PR 0e: Frontend V2 shell

| File | Change |
|---|---|
| `src/app/w/[orgSlug]/layout.tsx` (new) | V2 shell: icon rail, rooms panel placeholder, top bar, center, right rail (spec 10.1) with empty states |
| `src/app/w/[orgSlug]/page.tsx` (new) | Empty Cockpit |
| `src/app/w/signin/page.tsx`, `src/app/w/first-login/page.tsx`, `src/app/w/reset-password/page.tsx` (new) | V2 auth screens at `/w/signin`, `/w/first-login`, `/w/reset-password` (E22; V1 `/signin` untouched). Static segments win over `[orgSlug]`, and those three words become reserved org slugs |
| `src/lib/axios.ts` | Fix F8 (E22a): no `https://api.flobrain.ai` fallback; dev defaults to `http://127.0.0.1:8000`; a production build fails if `NEXT_PUBLIC_API_URL` is unset (checked in `next.config.ts` at build time) |
| `src/lib/v2/client.ts`, `src/lib/v2/schema.d.ts` (generated) | Typed wrapper over the existing Axios instance (E23); `npm run gen:api` script with `openapi-typescript` |
| `src/lib/v2/auth/WorkspaceGuard.tsx` | `GET /api/v2/me` bootstrap, redirect rules (not signed in, first login, non-company user) |
| `src/i18n/` + `messages/en.json`, `messages/ar.json` (new) | `next-intl` (E24), `dir` from locale, logical CSS properties only in V2 components |
| `src/styles/v2-tokens.css` (new) | Semantic tokens (`--fb-v2-accent`, `--fb-v2-surface`, ...) mapped to the existing page-scoped values for `.dark` and `.light` (AUDIT F9); V1 tokens untouched |
| `src/components/v2/states/` (new) | `Loading`, `Empty` ("No data yet"), `NoAccess`, `ErrorState` (retry) |
| `src/components/v2/ui/` (new) | shadcn primitives added by the CLI into a V2 folder (the existing alias points at `components/layout`, so V2 sets its own alias) |
| `eslint.config.mjs` | `react/no-danger` (E25); stop ignoring `*.test.*` for V2 folders only |
| `playwright.config.ts`, `e2e/` (new) | Playwright harness; journey 1 (onboarding) skeleton using the seed command |
| repo root `.github/workflows/website-ci.yml` | Add `npm test -- --run` (Vitest) and a Playwright job against a Django service container |

### PR 0f: Staging and CD (files only)

| File | Change |
|---|---|
| `docs/v2/INFRA_CHANGES.md` (new) | Staging stack, `/healthz` target group switch then strict `ALLOWED_HOSTS`, gunicorn command (E26), one-off migration task (Q28), `CORS_ALLOWED_ORIGINS`, `DRF_NUM_PROXIES=1`, new secrets, Redis (Q7) |
| repo root `.github/workflows/backend-deploy.yml` (new, disabled) | Build image on merge, deploy to staging, smoke test, manual promotion to prod |
| `docs/v2/RUNBOOK.md` (new) | Deploy, rollback, migrations, restore from RDS backup |
| `docs/v2/CHANGELOG.md`, `docs/v2/TECH_DEBT.md` (new) | Phase 0 entries; TECH_DEBT seeded from AUDIT.md section 6 |

### Phase 0 migrations

| App | Migration | Contents |
|---|---|---|
| `users` | `0002_user_is_platform_admin` | `is_platform_admin` bool default false |
| `users` | `0003_user_v2_profile` | V2 profile fields (all nullable or defaulted) |
| `users` | `0004_passwordresettoken` | `PasswordResetToken` |
| `organizations` | `0001_initial` | All Phase 0 models, unique constraints (`org`,`user`), (`team`,`user`), (`org`,`name`) |
| `telemetry` | `0001_initial` | `UsageEvent`, `AITrace`, `ProductEvent`, `FeedbackItem` |

### Phase 0 endpoints (all under `/api/v2/`)

| Method | Path |
|---|---|
| POST | `auth/signin`, `auth/refresh`, `auth/signout` (Bearer required), `auth/password/forgot`, `auth/password/reset`, `auth/first-login` |
| GET | `me` |
| GET, POST | `orgs/{org}/grants`; DELETE `orgs/{org}/grants/{id}` |
| GET, POST | `orgs/{org}/permission-requests`; POST `orgs/{org}/permission-requests/{id}/approve`, `.../reject` |
| GET | `orgs/{org}/audit-events` |
| POST | `orgs/{org}/events`, `orgs/{org}/feedback`; GET `orgs/{org}/admin/feedback`, `orgs/{org}/admin/analytics` |
| GET | `/healthz` (root, not under `/api/v2/`) |

Acceptance: spec Phase 0 list, plus Django backend CI green.

---

## Stage A

### Phase 1: Organization, team leads, member lifecycle

Blocking: Q10 (org model), Q33 (contact visibility), Q34 (existing V1 accounts).

| Area | Files |
|---|---|
| Backend | `organizations/views/members.py`, `teams.py`, `projects.py`; `organizations/services/members.py` (register with temp password email, status change, deactivate → revoke tokens via `password_changed_at` bump); `integrations_hr/` (HMAC webhook `POST /api/v2/integrations/hr/applicants`, `HR_WEBHOOK_SECRET`) |
| Frontend | `src/app/w/[orgSlug]/directory/`, `members/[userId]/`, `mission-control/` (shell), `settings/access/` (requests and grants) |
| Migrations | `organizations/0002_membership_pending_and_profile` (if fields missing from 0001), `organizations/0003_hr_intake` (applicant source/reference fields) |
| Endpoints | `GET/POST orgs/{org}/members`, `PATCH orgs/{org}/members/{user}`, `GET/POST orgs/{org}/teams`, `GET/PATCH orgs/{org}/teams/{team}`, `GET orgs/{org}/teams/{team}/members`, `GET/POST orgs/{org}/projects`, `GET/PATCH orgs/{org}/projects/{project}`, `POST integrations/hr/applicants` |

### Phase 2: Tasks

| Area | Files |
|---|---|
| Backend | new app `tasks/` (`Task`, `TaskAssignment`, `TaskActivity`, `ProjectTemplate`), services enforcing Decision 2; Mission Control aggregates in `tasks/selectors.py` |
| Frontend | `src/components/v2/tasks/` (Kanban with keyboard moves, filters, assign panel), `My Tasks`, Mission Control widgets |
| Migrations | `tasks/0001_initial` (indexes on `org`, `status`, `due_date`; unique (`task`,`user`)) |
| Endpoints | `GET/POST orgs/{org}/tasks`, `PATCH/DELETE .../tasks/{task}`, `POST .../tasks/{task}/move`, `POST .../tasks/{task}/assign`, `GET/POST orgs/{org}/project-templates`, `POST orgs/{org}/projects/from-template`, `GET orgs/{org}/mission-control` |

### Phase 3: Time tracking, workload, calendar

| Area | Files |
|---|---|
| Backend | new app `timetracking/` (`Tag`, `TimeEntry` with partial unique index on `user` where `ended_at IS NULL`); reports in `timetracking/reports.py`; calendar selector in `tasks/selectors.py` (meetings join in Phase 5) |
| Frontend | top-bar timer (`src/components/v2/timer/`), reports pages, Workload tab, room Calendar tab (task deadlines) |
| Migrations | `timetracking/0001_initial` |
| Endpoints | `GET/PATCH orgs/{org}/timer`, `POST orgs/{org}/timer/start`, `POST orgs/{org}/timer/stop`, `GET/POST orgs/{org}/time-entries`, `PATCH/DELETE .../{id}`, `GET orgs/{org}/time-reports/me`, `GET orgs/{org}/time-reports/team/{team}`, `GET orgs/{org}/dashboard/me`, `GET orgs/{org}/calendar` |

---

## Stage B

### Phase 4: Rooms, chat, live translation

Blocking: Q7 for realtime only (polling ships first).

| Area | Files |
|---|---|
| Backend | new app `rooms/` (`Room`, `RoomMember`, `RoomMessage`, `MessageTranslation`, `Announcement`), signals syncing team/project membership to rooms; translation via `brain/llm` V2 entry point writing `UsageEvent`/`AITrace`; `realtime/` (Channels consumer + ticket endpoint) behind the `realtime` flag, inactive until INFRA approval |
| Frontend | rooms sidebar, room chat with cursor pagination and polling hook (`useRoomMessages`), timestamps per Decision 13, translation toggle |
| Migrations | `rooms/0001_initial` (unique team room, unique project room, unique direct pair) |
| Endpoints | `GET/POST orgs/{org}/rooms`, `GET/PATCH orgs/{org}/rooms/{room}`, `GET .../rooms/{room}/members`, `GET/POST .../rooms/{room}/messages`, `PATCH/DELETE .../messages/{id}`, `GET orgs/{org}/rooms/search`, `GET/POST orgs/{org}/announcements`, `POST .../announcements/{id}/unpin`, `POST realtime/ticket`, `GET orgs/{org}/notifications`, `POST .../notifications/read` (notifications app created here: `notifications/0001_initial`) |

### Phase 5: Voice/video and meeting intelligence

Blocking: Q2 (provider), Q14 (transcription), Q17 (job queue for transcription).

| Area | Files |
|---|---|
| Backend | new app `meetings/` (`Meeting`, `Recording`, `Transcript`, `MeetingSummary`), provider adapter interface in `meetings/providers/`, transcription and summary jobs |
| Migrations | `meetings/0001_initial`, `meetings/0002_transcript_summary` |
| Endpoints | `GET/POST orgs/{org}/rooms/{room}/meetings`, `GET .../rooms/{room}/recordings`, `POST orgs/{org}/recordings/{id}/transcribe`, `GET .../transcript`, `POST .../summarize`, `GET orgs/{org}/meetings/{id}/summary`, `POST .../action-items/{item_id}/to-task` |

### Phase 6: External tools, docs, files, search

| Area | Files |
|---|---|
| Backend | new apps `docs/` (`Document`, `DocumentRevision`, `StoredFile`, presigned S3 uploads) and `integrations/` (`ExternalTool` now; `Credential` in Phase 7); global search selector in `search/` (Postgres full text on `content_text`, room messages, tasks) |
| Migrations | `docs/0001_initial`, `integrations/0001_external_tools` |
| Endpoints | `GET/POST/PATCH/DELETE orgs/{org}/tools`, `GET/POST orgs/{org}/rooms/{room}/docs`, `GET/PATCH orgs/{org}/docs/{doc}`, `GET orgs/{org}/docs/search`, `POST orgs/{org}/files/presign`, `POST orgs/{org}/files/{id}/complete`, `GET orgs/{org}/search` |

### Deferred from Stage B review (do not build now)

These belonged to later phases or are blocked by open questions. Moved here instead of shipping placeholders.

- **Phase 7:** live translation is PR **7j** in `PHASE_7_PLAN.md` (flag `live_translation` default off, short text through the provider, original kept). Room AI chat is PR **7d**.
- **Q2 / Phase 5 follow-up:** real voice/video SDK, join URLs, On Call presence, LIVE badge, min/max call window, screen share, meeting-started notification, recording notice, focused video viewer.
- **Q14 / Q17:** real transcription/summarize workers (not local stubs).
- **Q7 / INFRA:** Django Channels consumer + Redis; realtime ticket stays 501/503 until then.
- **No AWS:** S3 presigned uploads stay local (`/local-uploads/`, `/media/local/`) until infra approval.
- **Phase 6 polish:** rich-text editor, autosave debounce, revision browser, tool reorder UI.
- **Phase 4 polish:** avatars, active-member strip, dedicated message-search UI, timer `room` FK. Room tabs still to connect when the screen is room-filtered: Report, Team. Recordings stay on the meetings page until that tab is room-scoped.
- **Phase 9:** highlight clips.

---

## Stage C (starts only after Stage A permission tests are complete)

### Phase 7: AI core

Blocking: Q1 (`/process` field contract), Q26 (which model embeds). Q13's location is known; HTTPS and auth are still an infra change before any credential is sent. Q35 is answered: pgvector on the existing RDS, behind a flag. Background work uses a PostgreSQL queue (no Redis, no SQS).

| Area | Files |
|---|---|
| Memory wiring | new app `knowledge/` (`KnowledgeItem`); indexing jobs per source type on a **PostgreSQL-backed queue**; reuse `memory/sorter.py`, `tier_2.hybrid_search`, `context_assembler.py`; fix the assembler's `vault_uri` call; vectors carry `org_id`, `visibility`, `room_id`, `team_id` so filtering happens before ranking (E16) |
| pgvector | Additive migration only: `CREATE EXTENSION IF NOT EXISTS vector`, behind a flag. If the extension is missing, memory search shows "Not configured". Prefer HNSW with conservative parameters (`db.t3.micro`, 1 GB). Do not build this before Phase 7 |
| AI threads | `brain/models.py`: nullable `room`, `buddy`, `org` FKs on `Chat`; V1 views filter `room IS NULL AND buddy IS NULL` in the same PR (spec 6.10) |
| Provider layer | `ModelProvider` in `brain/llm/` with two adapters, selected by `AI_PROVIDER_BACKEND`. Default **`multimodal_legacy`**: wrap today's V1 call only. Detect the "Echoing input" HTTP 200 fallback and raise a provider error; never store it as a reply or as memory. Do not send V2 org documents, memory, or files through it; those features use `direct` or show "Not configured". **`direct`**: Django calls the provider over HTTPS with a platform key or the org's BYOK credential. Local dev may set `direct` from an uncommitted `.env`. V1 call paths stay on `multimodal_legacy` unchanged |
| BYOK and plugins | `integrations/models.py` `Credential` with `integrations/crypto.py` (E20); Notion plugin reader |
| Budgets | `billing_usage/` or `telemetry/`: `Budget`, `PriceTable`, enforcement in the AI request path (platform credentials only) |
| Migrations | `brain/0003_chat_org_room_buddy`, `knowledge/0001_initial`, a separate `CREATE EXTENSION IF NOT EXISTS vector` migration, `integrations/0002_credential`, `telemetry/0002_budget_pricetable` |
| Endpoints | `GET orgs/{org}/ai/models`, `GET/POST orgs/{org}/rooms/{room}/ai/threads`, `POST orgs/{org}/ai/threads/{thread}/send`, `GET orgs/{org}/usage`, `GET/POST/PATCH/DELETE orgs/{org}/credentials`, `POST orgs/{org}/knowledge/ask`, `GET/PUT orgs/{org}/budgets`, `GET orgs/{org}/budgets/status` |

### Phase 8: Buddies, Buddy Builder, approved actions, auto reports

| Area | Files |
|---|---|
| Backend | new apps `buddies/` (`Buddy`, `BuddyPin`, seeds) and `actions/` (`ToolDefinition`, `ActionProposal`, `AutoReport`, tool executors per key), `agents/` (`AgentSchedule`, `AgentRun`), `skills` models (`SkillTag`, `MemberSkill`) in `organizations` |
| Migrations | `buddies/0001_initial`, `buddies/0002_seed_buddies` (data migration, FloLabs org only, reversible), `actions/0001_initial`, `agents/0001_initial`, `organizations/000x_skills` |
| Endpoints | spec Section 7 "Actions and reports", buddies, agent schedules, assignment suggestions, member skills |

### Phase 9: Content Studio Buddy

Blocking: Q15, Q16, Q18; worker token and JarvisLabs access.

| Area | Files |
|---|---|
| Backend | new app `content_studio/` (spec 6.16 models), connector registry `content_studio/connectors/`, worker API `workers/` with `WorkerToken` |
| Migrations | `content_studio/0001_initial`, `content_studio/0002_floq_template` (data), `workers/0001_initial` |
| Endpoints | spec Section 7 "Content Studio" and "Render workers" |

---

## Stage D

### Phase 10: Cockpit views, Arabic/RTL, PWA, desktop shell
- Backend: new app `workspace/` (`CockpitLayout`), `GET/PUT me/cockpit-layout`, `PATCH me/presence`; push subscription model in `notifications/` (`notifications/000x_push_subscription`).
- Frontend: Focus/Custom modes, full Arabic catalog, RTL visual checks in Playwright, `manifest.webmanifest`, service worker, Web Push (VAPID keys), low-bandwidth mode with an offline outgoing-message queue.
- Migrations: `workspace/0001_initial`.

### Phase 11: Profile, notifications, learning, certificates, portfolio
- Blocking: Q6, Q19.
- New app `learning/` (`LearningPath`, `Quiz`, `QuizAttempt`, `Certificate`, `PortfolioItem`, `Mentorship`, `MentorNote`, `Cohort`); `NotificationPreference` in `notifications/`.
- Public routes outside `/api/v2/`: `GET /verify/{slug}`, `GET /p/{portfolio_slug}`.
- Migrations: `learning/0001_initial`, `notifications/000x_preferences`.

### Phase 12: Commission and leads
- Blocking: Q5.
- New app `commissions/` (`Lead`, `Commission`), flag `commissions`.
- Migrations: `commissions/0001_initial`.
- Endpoints: `GET/POST orgs/{org}/leads`, `PATCH .../leads/{id}`, `GET orgs/{org}/commissions/summary`.

---

## Stage E

### Phase 13: Pulse
- New app `pulse/` (`EvalSuite`, `EvalCase`, `EvalRun`, `EvalResult`, `RoutingPolicy`, `Incident`); SSE endpoint authenticated by realtime ticket.
- Migrations: `pulse/0001_initial`.

### Phase 14: Status page, public API, webhooks, MCP
- New app `platform_api/` (`PersonalAccessToken`, `WebhookEndpoint`, `WebhookDelivery`, `ExternalAgentServer`); `/api/public/v1/` URLconf; MCP server as a separate small service (decided in the phase); status page as a separate static deployment (INFRA_CHANGES).
- Blocking: Q24.
- Migrations: `platform_api/0001_initial`.

### Phase 15: Integrations and meeting bot
- Connector SDK in `integrations/connectors/`; `MeetingBotSession` in `meetings/`.
- Blocking: Q23.
- Migrations: `meetings/000x_meeting_bot`, `integrations/000x_connectors`.

### Phase 16: Privacy center and external readiness
- New app `privacy/` (`PrivacySettings`, `DataExportJob`, `RetentionPolicy`); retention jobs delete vectors too.
- Blocking: Q20.
- Migrations: `privacy/0001_initial`.

### Phase 17: Enterprise and commercial readiness
- New apps `sso/` (`SSOConnection`, `SCIMToken`, SCIM 2.0 at `/scim/v2/`), `billing/` (`Plan`, `Subscription`, `UsageInvoiceLine`, Stripe webhook), `OrgPolicy` in `organizations/`, `MarketplaceItem` in `marketplace/`; memory export job; sovereign package (Helm/Terraform) under a new repo-root `deploy/` folder.
- Blocking: Q21, Q22, Q25, Q37.
- Migrations: `sso/0001_initial`, `billing/0001_initial`, `organizations/000x_orgpolicy`, `marketplace/0001_initial`.

---

## New Django apps (summary)

| App | Phase | Main models |
|---|---|---|
| `organizations` | 0 | Organization, OrgMembership, Team, TeamMembership, Project, ProjectMembership, PermissionGrant, PermissionRequest, AuditEvent |
| `telemetry` | 0 | UsageEvent, AITrace, ProductEvent, FeedbackItem (+ Budget, PriceTable in 7) |
| `tasks` | 2 | Task, TaskAssignment, TaskActivity, ProjectTemplate |
| `timetracking` | 3 | Tag, TimeEntry |
| `rooms` | 4 | Room, RoomMember, RoomMessage, MessageTranslation, Announcement |
| `notifications` | 4 | Notification (+ preferences, push subscriptions later) |
| `meetings` | 5 | Meeting, Recording, Transcript, MeetingSummary (+ MeetingBotSession in 15) |
| `docs` | 6 | Document, DocumentRevision, StoredFile |
| `integrations` | 6 | ExternalTool (+ Credential in 7) |
| `knowledge` | 7 | KnowledgeItem |
| `buddies`, `actions`, `agents` | 8 | Buddy, BuddyPin; ToolDefinition, ActionProposal, AutoReport; AgentSchedule, AgentRun |
| `content_studio`, `workers` | 9 | Spec 6.16 models; WorkerToken |
| `workspace` | 10 | CockpitLayout |
| `learning` | 11 | Spec 6.17 models + mentorship, cohorts |
| `commissions` | 12 | Lead, Commission |
| `pulse` | 13 | Eval*, RoutingPolicy, Incident |
| `platform_api` | 14 | PersonalAccessToken, WebhookEndpoint, WebhookDelivery, ExternalAgentServer |
| `privacy` | 16 | PrivacySettings, DataExportJob, RetentionPolicy |
| `sso`, `billing`, `marketplace` | 17 | Spec 6.19 models |

Existing apps extended: `users` (Phase 0), `brain` (Phase 7), `memory` (Phase 7 fixes), `model_registry` (Phase 0 permissions), `dashboard` (Phase 0 flags).

---

## What happens right after approval

1. Create `v2/phase-0-foundation` from `main`.
2. PR 0a (CI + test discovery fix), then 0b (P0 fixes), in that order, because 0b changes V1 behaviour and needs CI already in place.
3. Ask for production answers to Q11, Q12, Q27, Q28 while 0c to 0f are in review.
