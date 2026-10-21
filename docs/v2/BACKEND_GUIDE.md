# FloBrain backend guide

Audience: a backend developer joining the team. Read this before your first PR. It describes the Django backend in `flobrain-core/backend` as it is in the code today, and the rules that keep V1 working and V2 safe.

Paths below are relative to `flobrain-core/backend/` unless they start with the repo root (`docs/`, `deploy/`, `.github/`, `run-demo.sh`). The frontend has its own guide: [`FRONTEND_GUIDE.md`](FRONTEND_GUIDE.md).

Other docs this guide points to: `PLAN.md`, `DECISIONS.md` (spec decisions 1 to 51, engineering decisions E1 to E39), `RUNBOOK.md`, `SECURITY_REVIEW.md`, `awssupport.md`, `INFRA_CHANGES.md`, `multimodalsupport.md`, `DEMO.md`, `CHANGELOG.md`, `TECH_DEBT.md`, `features/*.md`, `compliance/`.

## Contents

1. [What the backend is](#1-what-the-backend-is)
2. [App map](#2-app-map)
3. [Request lifecycle](#3-request-lifecycle)
4. [Tenancy, roles and permissions](#4-tenancy-roles-and-permissions)
5. [Feature flags and plans](#5-feature-flags-and-plans)
6. [AI layer](#6-ai-layer)
7. [Actions and approvals](#7-actions-and-approvals)
8. [Async work and scheduling](#8-async-work-and-scheduling)
9. [Cross-cutting helpers](#9-cross-cutting-helpers)
10. [Data and migrations](#10-data-and-migrations)
11. [Demo mode](#11-demo-mode)
12. [Testing](#12-testing)
13. [Deploy and environments](#13-deploy-and-environments)
14. [How to add a feature](#14-how-to-add-a-feature)
15. [Rules](#15-rules)
16. [Known gaps and tech debt](#16-known-gaps-and-tech-debt)

---

## 1. What the backend is

### 1.1 FloBrain and the backend's role

FloBrain V2 is a workspace for organizations: members, teams and projects, tasks, time tracking, rooms and chat, meetings, documents, search, and AI "buddies" that can propose actions a person approves. The Django backend is the only source of truth for all of it. It owns the data, every permission check, every AI call, every encrypted secret and every outbound call. The website (`flobrain-website`, Next.js) only calls the API.

E3 in `DECISIONS.md`: the backend source of truth is `flobrain-core/backend`. Do not extend `flobrain-core/api`, `flobrain-core/core`, `flobrain-core/workflow-db`, `flobrain-core/manage.py` or `flobrain-cloud/`.

### 1.2 V1 and V2 side by side

Both live in one Django project (`flobrain/settings.py`, root URLconf `flobrain/urls.py`).

| | V1 | V2 |
|---|---|---|
| Apps | `users`, `memory`, `dashboard`, `brain`, `model_registry`, `contact` | everything else in `INSTALLED_APPS`, plus V2 parts of `users` (`users/v2/`) and `brain` (`brain/v2_urls.py`, `brain/v2_views.py`) |
| URLs | `api/auth/register/`, `api/auth/signin/`, `api/auth/signout/`, `api/auth/refresh/`, `api/profile/...`, `api/settings/...`, `api/memory/graph/`, `api/memory/nodes/<pk>/`, `api/memory/save/`, `api/dashboard/health/`, `api/dashboard/memory-activity/`, `api/dashboard/error-logs/`, `api/brain/chats/...`, `api/contact/` | `api/v2/...` mounted from `flobrain/urls_v2.py` |
| Auth | Manual user lookup (`users.jwt_utils.get_user_from_request`), global `REST_FRAMEWORK` defaults | `BearerJWTAuthentication` set on the `V2APIView` base |
| AI | `brain.llm.MultimodalLLMAdapter.generate()` calls the multimodal service (`MULTIMODAL_SERVICE_URL`, `POST /process`) | `brain.llm` providers: `direct` (OpenAI-compatible), BYOK, demo model. See section 6 |

The multimodal service is an external service owned by another team (EC2 in a second AWS account, plain HTTP). `multimodalsupport.md` describes the contract and its problems. V2 features that carry org content never send it there (E29).

Rule E4: V2 is isolated from V1 by construction. Global `REST_FRAMEWORK` defaults are not changed because V1 relies on them. V1 paths and response shapes do not change (`PLAN.md` section 0).

### 1.3 URL layout

`flobrain/urls.py` mounts, in this order:

| Mount | What |
|---|---|
| `admin/` | Django admin |
| `api/v2/` | `flobrain/urls_v2.py`, which includes one `urls.py` per V2 app (`users.v2.urls`, `organizations.urls`, ... `compliance.urls`) |
| `platform_api.public_urls` | Public API `api/public/v1/...` (PAT auth), status page `api/public/status...`, MCP endpoint `api/mcp`, MCP OAuth (`.well-known/oauth-protected-resource`, `.well-known/oauth-authorization-server`, `oauth/register`, `oauth/authorize`, `oauth/token`, `oauth/revoke`) |
| `learning.public_urls` | `api/public/verify/<slug>`, `api/public/certificates/public-key`, `api/public/portfolio/<slug>` |
| `sso.scim_urls` | SCIM 2.0: `scim/v2/Users`, `scim/v2/Groups` |
| V1 app URLconfs | `users`, `memory`, `dashboard`, `brain`, `model_registry`, `contact` |
| `api/schema/`, `api/swagger/`, `api/redoc/` | drf-spectacular |

Inbound "hooks" from outside systems live under `api/v2/` and are unauthenticated at the DRF level; they verify a signature instead (section 9.5):

- `api/v2/integrations/hr/applicants` (n8n HR intake)
- `api/v2/billing/stripe/webhook`
- `api/v2/livekit/webhook`
- `api/v2/hooks/whatsapp/<connection_id>`, `api/v2/hooks/telegram/<connection_id>`
- `api/v2/hooks/slack/events`, `.../slack/commands`, `.../slack/interactions`, `api/v2/hooks/teams/messages`
- `api/v2/hooks/automations/<workflow_id>`

`GET /healthz` is answered by middleware before URL routing (section 3.1).

### 1.4 Stack

From `requirements.txt` (ranges, not pins, except where shown):

| Package | Version | Used for |
|---|---|---|
| Django | `>=5.2,<6.0` | Framework |
| djangorestframework | `>=3.15` | API views, throttles, exceptions |
| drf-spectacular | `>=0.27` | OpenAPI at `/api/schema/` |
| django-cors-headers | `>=4.0` | CORS |
| psycopg2-binary | `>=2.9` | PostgreSQL |
| PyJWT | `>=2.0` | JWTs in `users/jwt_utils.py` (HS256) |
| djangorestframework-simplejwt | `>=5.5,<6.0` | Listed; V2 auth uses `users/jwt_utils.py` |
| cryptography | unpinned | AES-256-GCM in `integrations/crypto.py` |
| boto3 | unpinned | S3 (Content Studio storage) |
| dnspython | unpinned | DNS lookups (SSO domain verification) |
| pywebpush | `==2.0.3` | Web Push |
| lxml, signxml | `==6.1.3`, `==5.1.0` | SAML |
| pypdf, defusedxml | `==6.20.1`, `==0.7.1` | Imports |
| tiktoken | `>=0.5.0` | Token estimates (`telemetry.pricing.estimate_tokens`) |
| python-dotenv | `>=1.0` | Loads `flobrain-core/backend/.env` at settings import |
| pymongo, chromadb, networkx, SQLAlchemy, rank_bm25, zstandard, numpy, opencv-python-headless, reportlab, pydantic, prometheus_client | various | V1 memory code and older parts |
| celery, redis, django-redis | various | Installed but not used as the queue (E17) |

Python 3.11 (Dockerfile `python:3.11-slim`, CI `setup-python 3.11`).

`users.User` is a custom model (`users/models.py`), not Django's `AUTH_USER_MODEL`. It has `is_platform_admin`, `user_type`, `password_changed_at`, `must_change_password` and the V2 profile fields. In V2 views `request.user` is a `users.User` returned by `BearerJWTAuthentication`.

### 1.5 Run it locally

**One click (demo, SQLite).** From the repo root: `./run-demo.sh` (macOS, Linux) or `run-demo.bat` (Windows). It creates `flobrain-core/backend/.venv`, installs requirements, writes a random `CREDENTIALS_ENCRYPTION_KEY` to `flobrain-core/backend/.demo-key`, sets demo env (`DEMO_MODE=True`, `DEMO_AI=True`, `DB_ENGINE=sqlite`, `SQLITE_PATH=.../demo.sqlite3`, `EMBEDDINGS_BACKEND=fake`, `KNOWLEDGE_VECTOR_STORE=json` (SQLite has no pgvector), `CONTENT_STORAGE=local`, `DOCS_FILE_STORAGE=local`, ...), runs `migrate`, runs `seed_demo` on a fresh database, then starts `runserver 127.0.0.1:8000 --noreload` and the website on port 3000. Delete `demo.sqlite3` to start over. Details: `DEMO.md`.

**Manual, SQLite** (from `flobrain-core/backend`, bash):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DB_ENGINE=sqlite DEBUG=True ALLOW_INSECURE_AES_MASTER_KEY=1
export EMBEDDINGS_BACKEND=fake KNOWLEDGE_VECTOR_STORE=json   # search without pgvector or an embeddings server
export SECRET_KEY='<any local string, 32+ chars>'
python manage.py migrate
python manage.py create_org --name "FloLabs" --slug flolabs --owner-email you@example.com --all-features
python manage.py runserver
```

`create_org` prints a one-time temporary password for a new owner. `seed_v2_demo` (FloLabs org, 3 teams) and `seed_demo` (Nile Labs demo, needs `DEMO_MODE=True`) are the other seeds.

**Manual, PostgreSQL with pgvector.** Production and CI use PostgreSQL. Memory search needs pgvector (section 6.6). The repo's sovereign compose uses the image `pgvector/pgvector:pg16` (`deploy/sovereign/docker-compose.open-models.yml`); any PostgreSQL 15 or 16 with the `vector` extension works.

```bash
export DB_ENGINE=postgresql DB_HOST=localhost DB_PORT=5432 DB_NAME=flobrain_db DB_USER=flo_user DB_PASS='<local password>'
python manage.py migrate
```

`knowledge/migrations/0001_pgvector.py` runs `CREATE EXTENSION IF NOT EXISTS vector` only if the server offers it, and never fails the migration if it cannot.

Settings read from env (all in `flobrain/settings.py`): `DB_ENGINE` (`sqlite` or default PostgreSQL), `SQLITE_PATH`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`. A `.env` file next to `manage.py` is loaded automatically. Never commit it.

**Checks before a PR** (same as `.github/workflows/django-backend-ci.yml`):

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
python manage.py spectacular --file /tmp/schema.yml
```

### 1.6 Docker

- `Dockerfile`: `python:3.11-slim`, installs requirements and `postgresql-client`, `CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]`. Production still runs this command; the switch to gunicorn is an infra change (E26, `awssupport.md` 3.4).
- `docker-compose.yml` (local only): `db` (`postgres:15`, no pgvector), `web` (waits for Postgres, runs `migrate` then `runserver`, needs a `.env` file because of `env_file: .env`), `mongodb`, `redis`. V2 does not use Mongo or Redis. Running `migrate` on web start is fine locally and forbidden in production (section 10.3).
- `deploy/meetings/` (LiveKit, Egress, Whisper, meeting bot) and `deploy/sovereign/` (customer installs) are separate; see `awssupport.md` 3.12 and 3.13.

---

## 2. App map

Every app in `INSTALLED_APPS`, grouped by domain. `core_v2`, `realtime` and `search` are packages without models that are not in `INSTALLED_APPS`; their URLs are still mounted.

### Identity and organization

| App | Responsibility | Key models |
|---|---|---|
| `users` | V1 auth and profile; V2 auth endpoints in `users/v2/` (`auth/signin`, `auth/refresh`, `auth/signout`, `auth/password/forgot`, `auth/password/reset`, `auth/first-login`, `me`); `BearerJWTAuthentication`; `LastActiveMiddleware` | `User`, `PasswordResetToken`, plus unused V1 tables (`Role`, `UserRole`, `Group`, ...) |
| `organizations` | Tenancy, roles, permission engine, grants and requests, audit, member lifecycle, skills, org AI policy, HR applicants | `Organization`, `OrgMembership`, `Team`, `TeamMembership`, `Project`, `ProjectMembership`, `PermissionGrant`, `PermissionRequest`, `AuditEvent`, `HRApplicant`, `SkillTag`, `MemberSkill`, `OrgPolicy` |
| `integrations_hr` | Signed HR intake webhook that creates pending members | none (uses `organizations.HRApplicant`) |
| `sso` | OIDC and SAML sign-in, domain verification, SCIM 2.0 | `SSOConnection`, `SSOState`, `SAMLRequest`, `SSOLoginCode`, `SCIMToken`, `SCIMGroupMap` |
| `console` | Platform console; read-only, time-limited support sessions (impersonation) | `ImpersonationSession` |
| `workspace` | Cockpit layout per user | `CockpitLayout` |

### Collaboration

| App | Responsibility | Key models |
|---|---|---|
| `tasks` | Tasks, assignment, activity, reminders, project templates, Mission Control | `Task`, `TaskAssignment`, `TaskActivity`, `TaskReminder`, `ProjectTemplate` |
| `timetracking` | Timer, time entries, reports | `Tag`, `TimeEntry` |
| `rooms` | Team, project, direct and group rooms; messages; translation; announcements; voice notes | `Room`, `RoomMember`, `RoomMessage`, `MessageTranslation`, `Announcement`, `VoiceNote` |
| `notifications` | In-app notifications, preferences, Web Push | `Notification`, `PushSubscription`, `NotificationPreference` |
| `meetings` | Meetings, LiveKit calls, recordings, transcripts, summaries, meeting bot | `Meeting`, `Recording`, `TrackEgress`, `Transcript`, `MeetingSummary`, `MeetingBotSession` |
| `docs_app` | Room documents, revisions, attachments | `Document`, `DocumentRevision`, `StoredFile` |
| `learning` | Learning paths, quizzes, certificates, portfolio, mentorship, cohorts | `LearningPath`, `PathProgress`, `Quiz`, `QuizAttempt`, `Certificate`, `PortfolioItem`, `Mentorship`, `MentorNote`, `Cohort` |
| `commissions` | Leads and commissions | `Lead`, `Commission` |
| `search` (not an app) | Global search (PostgreSQL full text, `icontains` on SQLite) | none |
| `realtime` (not an app) | Realtime ticket endpoint (503 when the flag is off, 501 when on; polling is the real path) | none |

### AI and buddies

| App | Responsibility | Key models |
|---|---|---|
| `brain` | V1 chat (`Chat`, `Message`); V2 AI threads and provider layer in `brain/llm/` | `Chat`, `Message` |
| `memory` | V1 memory graph (Mongo, tiers) | `TokenDictionary`, `MemoryNode`, `MemoryLink` |
| `model_registry` | Model list; writes need `is_platform_admin` (E13) | `AIModel` |
| `knowledge` | Chunking, embeddings, vector store, permission-filtered retrieval, knowledge ask | `KnowledgeChunk`, `KnowledgeVectorJSON` (+ raw `knowledge_vec_1024` table on pgvector) |
| `buddies` | Buddies, chat turns, Flo router, quality page, templates, seeds | `Buddy`, `BuddyPin`, `BuddyFeedback`, `BuddyRoute`, `BuddyRouteHop`, `BuddyAnswer` |
| `buddy_memory` | Facts buddies remember about a person, with consent | `MemoryItem`, `MemorySettings`, `MemoryPreference`, `MemoryDeclined` |
| `evals` | Buddy evaluation sets and quality gates | `EvalPolicy`, `EvalSet`, `EvalCase`, `EvalRun`, `EvalGateEvent` |
| `agents` | Scheduled agents | `AgentSchedule`, `AgentRun` |
| `actions` | Tool registry, proposals and approvals, team reports | `ToolDefinition`, `ActionProposal`, `EmailDraft`, `AutoReport` |
| `pulse` | AI quality console: evals, routing policy, alert rules | `EvalSuite`, `EvalCase`, `EvalRun`, `EvalResult`, `RoutingPolicy`, `AlertRule` |
| `content_studio` | Video projects, renders, consent, social publishing | `BrandKit`, `ContentTemplate`, `MediaAsset`, `ContentProject`, `RenderJob`, `EditDecisionList`, `ClipSuggestion`, `ConsentRecord`, `AssetPerson`, `SocialAccount`, `OAuthState`, `PublishJob` |
| `workers` | Worker API and tokens for GPU render workers and the meeting bot | `WorkerToken` |

### Automation and growth

| App | Responsibility | Key models |
|---|---|---|
| `automations` | Workflows, triggers, runs, approvals, daily brief | `Workflow`, `WorkflowRun`, `RunApproval`, `InboundHook`, `AutomationSettings`, `BriefOptOut` |
| `datasets` | Data buddy: datasets, questions to SQL, reports | `Dataset`, `SavedQuestion`, `Report`, `ReportRun` |
| `growth` | Academy, industry packs, AI allowance meter | `LessonProgress`, `AcademyBadge`, `InstalledPack` |
| `marketplace` | In-org marketplace of buddies and templates | `Listing`, `Install`, `Rating` |
| `imports` | Slack, Notion and Google Drive imports | `ImportRun`, `ImportedObject` |

### Integrations and channels

| App | Responsibility | Key models |
|---|---|---|
| `integrations` | External tool links, BYOK keys, write-back connectors (`integrations/write/`), credential crypto | `ExternalTool`, `AICredential` |
| `connectors` | Read connectors (GitHub live; others declared "not set up") | `Connection`, `ExternalItem`, `TaskLink` |
| `channels` | WhatsApp, Telegram, website chat, customer buddy | `ChannelConnection`, `ChannelLink`, `InboundEvent`, `CustomerSettings`, `CustomerKnowledge`, `CustomerConversation`, `CustomerMessage` |
| `bridges` | Slack and Microsoft Teams | `BridgeWorkspace`, `BridgeLink`, `BridgeThread`, `BridgeEvent`, `BridgeCard`, `BridgeOAuthState` |
| `einvoice` | ZATCA and ETA e-invoicing, data residency | `TaxProfile`, `Invoice`, `InvoiceLine`, `AuthorityEvent` |

### Platform and public API

| App | Responsibility | Key models |
|---|---|---|
| `platform_api` | PATs, public API, outbound webhooks, MCP server and OAuth, external agents (MCP client), MCP hub, status page and incidents, SSRF-safe HTTP (`net.py`), PII redaction (`pii.py`) | `PersonalAccessToken`, `WebhookEndpoint`, `WebhookDelivery`, `ExternalAgentServer`, `ExternalAgentHost`, `ExternalAgentCall`, `DemoInboxDelivery`, `StatusSubscription`, `Incident`, `OAuthClient`, `OAuthGrant`, `OAuthAuthorizationCode`, `OAuthAccessToken`, `OAuthRefreshToken`, `MCPServerPolicy`, `MCPCallLog` |
| `telemetry` | Usage, traces, product events, feedback, prices, budgets | `UsageEvent`, `AITrace`, `ProductEvent`, `FeedbackItem`, `PriceTable`, `Budget` |
| `dashboard`, `contact` | V1 dashboard and contact form | none |

### Billing

| App | Responsibility | Key models |
|---|---|---|
| `billing_v2` | Plans, subscriptions, entitlements and seat limits, Stripe webhook and checkout, workspace pricing | `Plan`, `Subscription`, `UsageInvoiceLine`, `StripeEvent`, `Invoice` |

### Compliance and privacy

| App | Responsibility | Key models |
|---|---|---|
| `privacy` | Privacy settings, personal data export, deletion requests, retention | `PrivacySettings`, `DataExportJob`, `DeletionRequest`, `RetentionPolicy` |
| `exports` | Owner-only org memory export | `MemoryExport` |
| `compliance` | SOC 2 and ISO 27001 readiness checks, access reviews, evidence, policies, trust center | `ComplianceProfile`, `ControlAttestation`, `AccessReview`, `AccessReviewItem`, `EvidencePackage`, `Policy`, `PolicyVersion`, `PolicyAck`, `TrustCenter`, `TrustRequest` |

### Infra

| App | Responsibility | Key models |
|---|---|---|
| `jobs` | PostgreSQL job queue and `run_jobs` worker | `Job` |
| `demo` | Demo org, demo sign-in, demo IdP, in-process ticker | `DemoAccount` |
| `core_v2` (package) | `V2APIView`, `V2PublicAPIView`, error handler, pagination, throttles, idempotency helper | none |

---

## 3. Request lifecycle

### 3.1 Middleware

`MIDDLEWARE` in `flobrain/settings.py`, in order:

1. `corsheaders.middleware.CorsMiddleware`
2. `flobrain.middleware.HealthCheckMiddleware`: answers `GET /healthz` with `200 ok` (text/plain) before host validation, so an ALB that sends the task IP as `Host` still passes (E18).
3. `SecurityMiddleware`, `SessionMiddleware`, `CommonMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`
4. `users.middleware.LastActiveMiddleware`: for paths under `/api/v2/`, updates `User.last_active` at most once a minute.
5. `MessageMiddleware`, `XFrameOptionsMiddleware`

### 3.2 Hosts and CORS

- `ALLOWED_HOSTS = ["0.0.0.0", "127.0.0.1", "localhost"]` plus the comma list in env `ALLOWED_HOSTS`. Production sets `*` today. Do not tighten it until the target group checks `/healthz` (`awssupport.md` 3.3).
- `CSRF_TRUSTED_ORIGINS` from env (comma list).
- CORS: allowlist from env `CORS_ALLOWED_ORIGINS`, default `http://localhost:3000,http://127.0.0.1:3000`. `CORS_ALLOW_ALL=True` is a rollout escape hatch only. The API uses Bearer tokens, not cookies.
- `DRF_NUM_PROXIES` sets `REST_FRAMEWORK["NUM_PROXIES"]` and `NUM_PROXIES` (E19). Set `1` behind the ALB. `organizations.flags.client_ip(request)` honours it for audit IPs.

### 3.3 Authentication classes

| Class | Where | Accepts |
|---|---|---|
| `users.authentication.BearerJWTAuthentication` | `V2APIView` default | `Authorization: Bearer <jwt>` from `users/jwt_utils.py` (HS256 with `SECRET_KEY`, access 1 hour, refresh 7 days). Refuses tokens issued before `password_changed_at`. Also accepts read-only impersonation tokens (`console/impersonation.py`): GET/HEAD/OPTIONS only, only `/api/v2/me` and `/api/v2/orgs/<that org>/...`, each request audited |
| `platform_api.authentication.PATAuthentication` | Public API `api/public/v1/...` | `Bearer fbp_...` personal access tokens. Re-checks expiry, password change, active membership and the `api_access` flag on every request; a failed membership or password check revokes the token. `require_scope(request, scope)` checks token scopes |
| `platform_api.oauth_mcp.MCPAuthentication` | `api/mcp` | `Bearer fba_...` MCP OAuth access tokens bound to the MCP resource URL, or falls back to PATs |
| `sso.scim.SCIMAuthentication` | `scim/v2/...` | SCIM tokens (hashed, compared with `hmac.compare_digest`) for verified domains of their own org |
| `workers.authentication.WorkerAuthentication` | `api/v2/workers/...` | `Authorization: Worker <token>` for render workers and the meeting bot (`IsWorker`) |
| SSO | `sso/start`, `sso/callback`, `sso/exchange`, `sso/saml/acs` | OIDC (state, nonce, PKCE, browser-bound one-time code) and SAML; the result is exchanged for normal V2 JWTs. `password_signin_blocked(user)` makes V2 sign-in answer 403 `sso_required` for enforced-SSO orgs |
| Demo sign-in | `api/v2/demo/signin` | Only when `DEMO_MODE=True` (404 otherwise); issues tokens for seeded `DemoAccount` users only |
| None | Hooks | Signature checks in the view (section 9.5) |

Token prefixes (`platform_api/models.py`): `fbp_` PAT, `fba_` OAuth access, `fbr_` OAuth refresh, `fbo_` authorization code, `fbc_` client id, `fbs_` client secret.

V2 sign-in also refuses users without an active membership (`organizations.services.members.v2_workspace_signin_allowed`, 403 `membership_inactive`). There is no V2 self-registration (Decision 9).

### 3.4 The V2 base views

`core_v2/views.py`:

```python
class V2APIView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle]

    def get_exception_handler(self):
        return v2_exception_handler


class V2PublicAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [V2AnonThrottle]
    ...
```

- `IsActiveOrgMember` (`organizations/permissions/drf.py`) resolves the org from the `org_id` URL kwarg (or, as a fallback, an `X-Org-Id` header), stores it on `request.org`, and requires an active `OrgMembership`. Platform admins pass.
- `HasPerm("key")` raises `PermissionDenied("Missing permission: key")` when `can()` fails. Views usually call it inline: `HasPerm("grants.create").has_permission(request, self)`.
- `get_scoped_or_404(user, perm_key, obj)` raises 404 when `can()` fails, for objects that must stay hidden.
- Org context is in the path: `/api/v2/orgs/{org_id}/...` (Decision 51), with `<uuid:org_id>` converters.

### 3.5 Throttles

| Throttle | Scope | Default rate | Setting |
|---|---|---|---|
| `core_v2.throttles.V2UserThrottle` | `v2_user` | `600/min` | `FLOBRAIN_V2_USER_THROTTLE` |
| `core_v2.throttles.V2AnonThrottle` | `v2_anon` | `60/min` | `FLOBRAIN_V2_ANON_THROTTLE` |
| `brain.throttles.AISendThrottle` | user | `30/min` | `FLOBRAIN_V2["AI_SEND_RATE"]` |
| `platform_api.public_views.PATThrottle`, `PATUserThrottle` | token, user | `120/min`, `300/min` | `PUBLIC_API_RATE`, `PUBLIC_API_USER_RATE` |
| `platform_api.oauth_mcp` `RegisterThrottle`, `TokenThrottle`, `AuthorizeThrottle`, `MetadataThrottle` | IP | in code | |
| `contact.views.ContactRateThrottle` (V1) | IP | `5/hour` | |

Some features also count with `cache.add` / `cache.incr` (for example the academy coach, 30 questions a day). All of these use Django's cache. There is no `CACHES` setting, so the cache is per-process LocMem (see section 9.6).

### 3.6 Error shape and status codes

`core_v2.errors.v2_exception_handler` turns every DRF exception into:

```json
{"error": "<code>", "details": "<text or field errors>"}
```

Views that return errors directly use the same shape: `Response({"error": "invalid", "details": ...}, status=400)`. `core_v2.errors.V2APIError(code, details, status_code)` is available for raising.

| Status | Code examples | When |
|---|---|---|
| 400 | `invalid` | Validation failed |
| 401 | `not_authenticated`, `authentication_failed`, `invalid_signature` | No or bad token; bad webhook signature |
| 403 | `permission_denied`, `sso_required`, `membership_inactive` | Caller is known but lacks a permission or an active membership |
| 404 | `not_found` | Object outside the caller's scope or hidden on purpose (others' personal keys, others' proposals, DMs, demo endpoints when demo is off) |
| 409 | `conflict`, `private_only`, `data_region`, `seat_limit`, `not_pending` | State conflict, or an org policy refuses it |
| 413 | `too_large` | Body over the limit |
| 429 | `throttled`, `budget_exceeded`, `rate_limited` | Rate limit or AI budget cap |
| 501 | `not_implemented`, `not_configured` | Feature flag off (E36), or a dependency is not set up (no provider, no storage, no key) |
| 502 | `provider_error` | The AI provider failed |
| 503 | `unavailable` | A dependency is down while the feature is on (E36) |

Use 404 rather than 403 whenever answering 403 would reveal that the object exists.

### 3.7 Pagination

- `core_v2.pagination.V2PageNumberPagination`: `page`, `page_size` (default 20, max 100). Response: `{"count", "next", "previous", "results"}`.
- `core_v2.pagination.V2CursorPagination`: ordered by `-created_at`, used for chat history.
- Many V2 list endpoints return a plain JSON array, or `{"results": [...]}` without counts. The website's `rowsOf()` helper (`flobrain-website/src/lib/v2/api.ts`) accepts both shapes. When you add a list endpoint, return either a plain array or a `results` key so `rowsOf()` keeps working.

---

## 4. Tenancy, roles and permissions

### 4.1 Model

- `Organization`: `id` (UUID), `name`, `slug` (unique), `settings` (JSON, holds `flags`), `is_active`.
- `OrgMembership`: one per (org, user). `org_role` is `owner`, `admin` or `member`. `employment_status` is `pending`, `active`, `paused`, `graduated`, `terminated` or `offboarding`. Only `active` counts (`is_active_member`). `feature_flags` (JSON) holds per-person flag overrides. `presence` is separate from status.
- `Team` and `TeamMembership` (`team_role` is `lead` or `member`). A "team lead" is anyone with `lead` on a team or `lead` on a project (Decision 1).
- `Project` and `ProjectMembership` (`source` is `team` or `direct`, E8).
- `users.User.user_type` is derived by `organizations.services.sync_user_type(user)` (E9): owner or admin anywhere → `company_adm`, lead → `company_lead`, active member → `company_member`, else `personal`. Memberships are the source of truth.
- `OrgPolicy` (one row per org, absent means defaults): `inference_scope` (`external_allowed` or `private_only`), `pii_redaction` (`off`, `external_only`, `always`), `data_region`.
- Inactive members cannot sign in, cannot receive new DMs or tasks, and keep read access to past work (Decision 7).

### 4.2 Permission registry

`organizations/permissions/registry.py`:

- `PERMISSION_CATALOG`: key → `{"label", "matrix"}`. `matrix` is `org`, `team` or `project`.
- `_MEMBER_DEFAULTS`: keys every member holds.
- `OWNER_ONLY_KEYS = {"exports.memory", "policy.manage", "sso.manage"}`: held only by an active owner. Not grantable (serializers refuse them), not in admin defaults, and not covered by the platform-admin bypass.
- `_ADMIN_DEFAULTS`: every key except `payroll.*` and `OWNER_ONLY_KEYS`.
- `ROLE_DEFAULTS`: owner gets every key; admin gets `_ADMIN_DEFAULTS`; member gets `_MEMBER_DEFAULTS`.

Keys are strings, not database rows (E6). A new key goes into `PERMISSION_CATALOG` and, if members should hold it, `_MEMBER_DEFAULTS`.

### 4.3 `can(user, perm_key, obj=None)`

`organizations/permissions/engine.py`. Order of checks:

1. Unknown key or no user → `False`.
2. Owner-only key → `True` only if `obj` is an `Organization` and the user is its active owner.
3. `user.is_platform_admin` → `True`.
4. Resolve scope from `obj`: an `Organization`; a `Team` (org from `team.org`); a `Project`; a dict `{"org": ..., "team": ..., "project": ...}`; or any object with `.org` (and optional `.team`, `.project`). `obj=None` → `False`.
5. No active membership in that org → `False`.
6. Role default holds the key: `org` matrix → `True`. `team` matrix → owner and admin `True`; with no team given `True`; else the user must be on that team. `project` matrix → owner and admin `True`; with no project given `True`; else project membership, or membership of the given team.
7. Active, unexpired `PermissionGrant` for this user and key: an `org` grant always matches; a `team` or `project` grant matches only when that team or project is passed in `obj`.
8. `mission.view` is derived: leads of any team (or of the given team) have it.
9. Team or project members get `team.view`, `project.view`, `task.view`, `task.write`, `time.view`, `time.write` for their own team or project.

Always pass the narrowest scope you have: `can(user, "task.write", team)` checks that team; `can(user, "task.write", org)` only checks the org-level role default.

Related helpers: `is_org_owner_or_admin(user, org)`, `visible_team_ids(user, org)` (`None` means all), and `org_permissions(user, org)`, a three-query equivalent of calling `can()` for every key at org level. `test_org_permissions_matches_can` keeps the two equal.

Lead powers are not in `ROLE_DEFAULTS`. Feature code checks the lead role directly where the spec says so: `report.generate` and the `reports.generate` tool (`buddies.services.holds_tool`), buddy share decisions (`can_decide_share`), task assignment rules (Decision 2), member status changes for their own team (Decision 8).

### 4.4 Grants and permission requests

- `PermissionGrant`: `org`, `grantee`, `perm_key`, `scope_type` (`org`, `team`, `project`; `room` exists in choices but `can()` does not use it), `scope_id`, `granted_by`, `expires_at`, `revoked_at`.
- `organizations.services.grant_permission(org, actor, grantee, perm_key, scope_type=..., scope_id=..., days=..., expires_at=..., request=...)` creates the grant and writes `perm.grant` to the audit log.
- `POST /orgs/{org}/grants` (needs `grants.create`): the grantee must be an active member, not yourself; you can only grant what you hold at that scope (`can(request.user, key, scope_obj)`, else 403); granting a key the grantee's role already has → 409 `conflict`. `MAX_GRANT_DAYS = 365`.
- `DELETE /orgs/{org}/grants/{id}` (needs `grants.revoke`) sets `revoked_at` and audits `perm.revoke`.
- `PermissionRequest` (`pending`, `approved`, `rejected`): members ask for a key (`permission_requests.create`); a decider who holds that key at that scope approves (`permission_requests.decide`), which calls `decide_request()` and creates the grant (Decision 29). Duplicates and already-decided requests → 409.
- `GET /orgs/{org}/permissions` (`PermissionCatalogView`) lists every key and marks owner-only keys as not grantable.

### 4.5 Permission keys and default holders

Generated from `organizations/permissions/registry.py` (85 keys). "Owner only" keys are never granted to anyone else. Team leads have no extra keys in `ROLE_DEFAULTS`; `mission.view` is derived for them by `can()`, and some features check the lead role directly (4.3).

**Org, people and access**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `org.members.view` | View organization members | org | yes | yes | yes |
| `org.members.manage` | Manage organization members | org | yes | yes | no |
| `org.members.view_contact` | View member contact details | org | yes | yes | no |
| `grants.create` | Create permission grants | org | yes | yes | no |
| `grants.revoke` | Revoke permission grants | org | yes | yes | no |
| `permission_requests.create` | Create permission requests | org | yes | yes | yes |
| `permission_requests.decide` | Approve or reject permission requests | org | yes | yes | no |
| `audit.view` | View audit events | org | yes | yes | no |
| `org.view` | View organization | org | yes | yes | yes |
| `org.manage_settings` | Manage organization settings | org | yes | yes | no |
| `team.view` | View team | team | yes | yes | yes |
| `team.manage` | Manage team | team | yes | yes | no |
| `project.view` | View project | project | yes | yes | yes |
| `project.manage` | Manage project | project | yes | yes | no |
| `hr.view` | View HR records | org | yes | yes | no |
| `hr.manage` | Manage HR records | org | yes | yes | no |
| `payroll.view` | View payroll | org | yes | no | no |
| `payroll.manage` | Manage payroll | org | yes | no | no |

**Work: tasks, time, inbox, mission control**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `time.view` | View time entries | team | yes | yes | yes |
| `time.write` | Write time entries | team | yes | yes | yes |
| `task.view` | View tasks | team | yes | yes | yes |
| `task.write` | Write tasks | team | yes | yes | yes |
| `inbox.view` | View inbox | org | yes | yes | yes |
| `inbox.act` | Act on inbox items | org | yes | yes | yes |
| `mission.view` | View Mission Control | team | yes | yes | no (leads: derived) |

**Collaboration: rooms, meetings, docs, search**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `chat.use` | Use chat | org | yes | yes | yes |
| `room.view` | View rooms | team | yes | yes | yes |
| `room.manage` | Manage rooms | org | yes | yes | no |
| `announcement.manage` | Pin announcements | org | yes | yes | no |
| `notification.view` | View notifications | org | yes | yes | yes |
| `meeting.view` | View meetings | team | yes | yes | yes |
| `meeting.manage` | Manage meetings | team | yes | yes | no |
| `docs.view` | View documents | team | yes | yes | yes |
| `docs.write` | Write documents | team | yes | yes | yes |
| `tools.manage` | Manage external tools | org | yes | yes | no |
| `search.use` | Use global search | org | yes | yes | yes |

**AI, memory, buddies, budgets**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `memory.view` | View memory | org | yes | yes | yes |
| `memory.write` | Write memory | org | yes | yes | no |
| `ai.use` | Use AI | org | yes | yes | yes |
| `knowledge.ask` | Ask org knowledge | org | yes | yes | yes |
| `ai.usage.view` | View AI usage | org | yes | yes | yes |
| `budget.view` | View AI budgets | org | yes | yes | no |
| `budget.manage` | Manage AI budgets | org | yes | yes | no |
| `credential.manage` | Manage org AI keys | org | yes | yes | no |
| `buddy.create` | Create private buddies | org | yes | yes | yes |
| `buddy.manage` | Manage and share buddies org-wide | org | yes | yes | no |
| `report.generate` | Generate team reports (leads) | team | yes | yes | no (leads: checked in code) |
| `pulse.view` | Use the Pulse console | org | yes | yes | no |
| `memory.manage` | Manage team memory and the organization's memory rules | org | yes | yes | no |
| `evals.manage` | Create evaluation sets and quality gates for buddies | org | yes | yes | no |

**Content Studio and social**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `content.use` | Use Content Studio (own projects) | org | yes | yes | yes |
| `content.manage` | Manage all Content Studio projects, brand kits and templates | org | yes | yes | no |
| `content.publish` | Publish or schedule social posts | org | yes | yes | no |
| `content.approve` | Approve social posts | org | yes | yes | no |
| `social.connect` | Connect social accounts | org | yes | yes | no |
| `consent.manage` | Manage the consent registry | org | yes | yes | no |

**Platform, integrations, automation**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `webhooks.manage` | Manage webhooks and API apps | org | yes | yes | no |
| `integrations.manage` | Manage external agents and integrations | org | yes | yes | no |
| `incidents.manage` | Manage the org's incidents | org | yes | yes | no |
| `automations.use` | Build and run your own automations | org | yes | yes | yes |
| `automations.manage` | Manage the organization's automations and their approval rules | org | yes | yes | no |
| `channels.manage` | Connect WhatsApp, Telegram and the website chat | org | yes | yes | no |
| `customers.view` | See customer conversations from the website chat and WhatsApp | org | yes | yes | no |
| `customers.reply` | Reply to customers and take over from the customer buddy | org | yes | yes | yes |
| `data.use` | Ask questions about the organization's datasets | org | yes | yes | yes |
| `data.manage` | Add, connect and remove datasets | org | yes | yes | no |
| `integrations.act` | Ask buddies to write to connected apps (each write is approved) | org | yes | yes | yes |
| `packs.install` | Install industry packs (buddies, automations, rooms) | org | yes | yes | no |
| `mcp.manage` | Manage which MCP servers and tools buddies and outside apps may use | org | yes | yes | no |
| `bridges.manage` | Connect Slack and Microsoft Teams | org | yes | yes | no |
| `imports.run` | Import from Slack, Notion and Google Drive | org | yes | yes | no |

**Policy, billing, enterprise**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `policy.manage` | Manage the org AI and data policy | org | owner only | no | no |
| `billing.view` | View billing and usage | org | yes | yes | no |
| `sso.manage` | Manage SSO and SCIM | org | owner only | no | no |
| `exports.memory` | Export the org's team and project memory | org | owner only | no | no |
| `marketplace.submit` | Offer your buddies and templates in the org marketplace | org | yes | yes | yes |
| `marketplace.manage` | Approve marketplace listings | org | yes | yes | no |
| `einvoice.view` | See e-invoices and their tax authority status | org | yes | yes | no |
| `einvoice.issue` | Prepare e-invoices (sending to the tax authority is approved) | org | yes | yes | no |
| `einvoice.manage` | Set up ZATCA and ETA onboarding, certificates and data residency | org | yes | yes | no |
| `compliance.view` | See compliance controls, evidence and access reviews | org | yes | yes | no |
| `compliance.manage` | Run access reviews, collect evidence and publish the trust center | org | yes | yes | no |

**Learning and commissions**

| Key | Label | Matrix | Owner | Admin | Member |
|---|---|---|---|---|---|
| `learning.manage` | Manage learning paths, quizzes, mentorships and cohorts | org | yes | yes | no |
| `certificates.issue` | Issue and revoke certificates | org | yes | yes | no |
| `commissions.manage` | Record commissions and change their amounts and statuses | org | yes | yes | no |

`GET /api/v2/orgs/{org}/me/access` (`organizations/views_access_me.py`) returns the caller's role, led teams, org-level keys and effective flags. It only reports; every endpoint still checks on its own.

---

## 5. Feature flags and plans

### 5.1 `effective_flag`

`organizations/flags.py`:

```python
def effective_flag(org, membership, key: str, default=False) -> bool:
    """Effective flag = plan entitlement AND org flag AND membership flag."""
```

- Org flags live in `Organization.settings["flags"]`.
- If the membership has the key in `OrgMembership.feature_flags`, the result is `org flag (default True) AND member flag`. This lets an admin turn a feature off for one person.
- Otherwise the result is the org flag (or `default`).
- If still on, `billing_v2.entitlements.allows(org, key)` must agree.

Flags are not env vars. They are per org (and per person). Every flag defaults to off. `create_org --all-features` and the demo seed turn them on.

### 5.2 Plans, entitlements and seats

`billing_v2/entitlements.py`:

- `plan_for(org)`: only when `BILLING_ENFORCE_ENTITLEMENTS=True` and the org has a `Subscription`. No subscription → no restriction. A canceled subscription → nothing allowed.
- `allows(org, key)`: the flag key must be in `plan.flags()`.
- `limit(org, name, default)`: the smaller of the default and the plan's limit.
- Seats: `seat_limit(org)`, `seats_used(org)` (terminated and graduated members do not count), `seat_blocked(org, adding_user_id=None, email="")`. Call `seat_blocked` inside `transaction.atomic()` on every path that adds or reactivates a member (invite, register, accept, reactivate, SCIM, HR intake); it locks the org row. On a full org return `seat_error(org, seats)` with status 409 (`{"error": "seat_limit", ...}`). A per-workspace plan (`workspace_subscription`) always caps at its included seats.

Keep `BILLING_ENFORCE_ENTITLEMENTS` off until plans exist (`awssupport.md` 3.2).

### 5.3 Flags

`KNOWN_FLAGS` in `organizations/views_access_me.py` is the list reported to the website. There is no `privacy_center` flag: the privacy page is a right (Decision 44).

| Flag | Gates | Checked in |
|---|---|---|
| `ai_actions` | Approval cards; buddies offered action tools | `actions/views.py`, `buddies/chat.py`, `channels/team.py`, `bridges/engine.py` |
| `api_access` | Public API and PATs | `platform_api/authentication.py`, `platform_api/views.py` |
| `assign_suggestions` | AI assignee suggestions | `organizations/views_skills.py` |
| `auto_reports` | Team reports | `actions/reports.py` |
| `budgets` | AI budgets and their enforcement; AI allowance meter | `telemetry/pricing.py`, `telemetry/v2_views.py`, `pulse/views.py`, `growth/views.py` |
| `buddies` | Buddies | `buddies/views.py` |
| `byok` | Customer AI keys (also needs `CREDENTIALS_ENCRYPTION_KEY`) | `integrations/v2_views.py`, `buddies/chat.py`, `brain/v2_views.py` |
| `content_studio` | Content Studio | `content_studio/access.py` |
| `live_translation` | Room message translation | `rooms/views.py` |
| `memory_search` | Knowledge indexing and retrieval | `knowledge/index.py`, `brain/v2_views.py`, `buddies/chat.py`, `platform_api/mcp.py` |
| `realtime` | Realtime ticket (503 off, 501 on) | `realtime/views.py` |
| `room_ai` | Room AI threads | `brain/v2_views.py` |
| `scheduled_agents` | Scheduled agents | `agents/service.py` |
| `social_publishing` | Social posts | `content_studio/views_publish.py`, `actions/service.py` |
| `voice_video` | Calls and recordings | `meetings/views.py`, `meetings/views_call.py` |
| `webhooks` | Outbound webhooks | `platform_api/webhooks.py`, `platform_api/views.py` |
| `learning` | Learning paths, quizzes, certificates | `learning/views.py` |
| `commissions` | Leads and commission | `commissions/views.py` |
| `pulse` | Pulse console | `pulse/views.py` |
| `integrations` | Read connectors | `connectors/views.py` |
| `meeting_bot` | Meeting assistant | `meetings/views.py` |
| `cockpit` | No backend check found (seeded only) | |
| `status_page` | Org incidents (with `incidents.manage`) | `platform_api/views.py` |
| `external_agents` | Outside AI agents (MCP client) | `platform_api/views_external.py`, `platform_api/external_agents.py` |
| `public_portfolio` | Public portfolio items | `learning/public_views.py` |
| `automations` | Workflows, daily brief | `automations/engine.py` |
| `channels` | WhatsApp, Telegram, website chat | `channels/` |
| `customer_buddy` | Customer buddy and inbox | `channels/` |
| `data_buddy` | Datasets and the `data.ask` tool | `datasets/services.py`, `datasets/tools.py` |
| `write_integrations` | Write-back connectors | `integrations/write/connections.py` |
| `flo_router` | Flo, the router buddy | `buddies/router.py` |
| `voice_notes` | Voice notes | `rooms/voice_views.py` |
| `academy` | Academy and AI coach | `growth/views.py` |
| `packs` | Industry packs (with `packs.install`) | `growth/views.py` |
| `mcp_hub` | MCP server governance and call log | `platform_api/mcp_hub.py` |
| `bridges` | Slack and Teams | `bridges/` |
| `einvoice` | E-invoicing | `einvoice/services.py`, `einvoice/tools.py` |
| `buddy_memory` | Buddy memory | `buddy_memory/services.py` |
| `buddy_evals` | Buddy evaluation gates | `evals/gate.py` |
| `imports` | Imports | `imports/services.py` |
| `compliance` | Compliance readiness | `compliance/views.py` |
| `workspace_pricing` | Per-workspace plans | `billing_v2/views.py` |

The usual gate pattern (see `commissions/views.py`, `growth/views.py`):

```python
def _gate(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "... is not enabled"}, status=501)
    return org, None
```

Check the flag first (501), then the permission (403), then the object scope (404).

---

## 6. AI layer

Everything is in `brain/llm/` unless noted. V1 keeps calling `MultimodalLLMAdapter.generate()` (`brain/llm/__init__.py`, `get_llm_adapter()`). V2 code never adds org content to that path.

### 6.1 Providers

`brain/llm/providers.py`:

- `ProviderResult`: `text`, `model`, `error_code`, token counts, `provider`, `tool_calls` (proposals only), `failed_attempts`. `ok` is `not error_code`.
- `LegacyMultimodalProvider`: wraps the V1 call. The HTTP 200 body that starts with `Perception system temporarily unavailable. Echoing input` becomes `provider_error` (E29).
- `DirectProvider(org=None).complete(messages, model=None, credential=None, tools=None)`: with a credential, an explicit model, or no org, calls `direct.chat_complete` once. Otherwise applies Pulse routing.
- `get_provider()`: `direct` when `AI_PROVIDER_BACKEND=direct`, else legacy. Default setting is `multimodal_legacy`. New V2 AI features use `DirectProvider` and show "not configured" rather than falling back to legacy (E29).

### 6.2 `direct` (OpenAI-compatible)

`brain/llm/direct.py`:

- `is_configured()`: `True` in demo AI mode; else needs `AI_DIRECT_BASE_URL`, `AI_DIRECT_API_KEY`, a non-empty `AI_DIRECT_MODEL_ALLOWLIST`, and an allowed base URL (HTTPS, or `http` only for localhost or a host in `AI_ALLOW_PLAINTEXT_HOSTS`).
- `chat_complete(messages, model=None, *, credential=None, tools=None)`: one `POST {base}/v1/chat/completions`. Missing config returns `not_configured` without opening a socket. The model must be in the allowlist (`AI_DIRECT_DEFAULT_MODEL` or the first entry is the default). HTTP errors map to `invalid`, `invalid_credential`, `rate_limited`, `provider_rejected`, `provider_unavailable`. At most 3 tool calls are read.
- With a `credential` (BYOK): the platform key and allowlist are not used, the model name is validated, the key is decrypted (`credential_unavailable` if it does not decrypt), and the request goes through `brain.llm.http.open_customer`, an opener that never follows redirects. No fallback to the platform key (Decision 20).

### 6.3 Routing

`brain/llm/routing.py`, `complete(call, org, messages, tools=None)`: for platform calls with no model chosen, try the org's `RoutingPolicy` primary then fallbacks (allowlisted, at most `MAX_ATTEMPTS = 3`). Candidates over `max_task_cost` are dropped (`cost_limit` if none is left); unhealthy ones (more than half failing over the last day with at least 5 calls, or p95 above the threshold) are skipped while a healthy one exists. Failover happens only on `provider_unavailable` or `provider_error`, never on a refusal. Skipped attempts are returned in `failed_attempts`.

### 6.4 Policy gate before every model call

`brain/llm/policy.py`, `check_ai(org, kind, target=None) -> str`. Empty string means go ahead. Kinds: `"direct"`, `"byok"` (target is the credential), `"legacy"`, `"embeddings"`, `"external_agent"`.

- Data residency first: `einvoice.residency.check_ai_residency` returns `data_region` when the org is pinned to a region and the AI host is outside it.
- Then `inference_scope(org)`: `private_only` if `AI_FORCE_PRIVATE_ONLY=True` or the org's `OrgPolicy` says so. In `private_only`, only hosts in `AI_SELF_HOSTED_HOSTS` may receive org content; legacy and external agents are always refused.
- Map the result to 409: `{"error": "private_only", ...}` or `{"error": "data_region", "details": refusal_message(org)}` (see `buddies/chat.py`).

### 6.5 Budgets and usage recording

- Record every V2 model call with `telemetry.writers.record_v2_provider_event(user, result, surface=..., org=..., chat=..., estimated=..., credential_source=..., operation=..., team=...)`. It writes `UsageEvent` rows (one extra error row per failed routing attempt) and an `AITrace`. Missing token counts are stored as `NULL`; use `telemetry.pricing.fill_missing_tokens(result, prompt_text(messages), output)` to estimate them.
- V1 chat writes through `record_v1_chat_best_effort`, which must never change the V1 response (E28).
- Before a platform-key call: `telemetry.pricing.budget_decision(org, user, credential_source, team=None)`. `code == "budget_exceeded"` → answer 429. `downgrade_model` set → switch to that cheaper platform model. BYOK calls are never metered. Budgets apply only when the `budgets` flag is on. `platform_budget_blocks()` is the older, block-only variant.
- Prices: `PriceTable` rows, looked up by `price_for(provider, model)`; `AI_DIRECT_PROVIDER` names the provider for `direct` calls.

### 6.6 BYOK

- Model `integrations.models.AICredential`: `owner` empty means an org key (managed by `credential.manage` holders); `owner` set means a personal key only that user sees (everyone else gets 404). Secret stored only as `ciphertext` with `key_version`; `last4` for display; `status` in `pending`, `active`, `rejected`, `indeterminate`, `disabled`, `expired`. `__repr__` never prints the secret.
- Rules in `integrations/credentials.py`: keys go only over HTTPS to a host in `BYOK_ALLOWED_HOSTS` (default list in settings), no redirects (E38); `resolve_for_use(user, org, credential_id)` refuses inactive keys; `payload(credential)` is the only shape returned to clients (no secret).
- Gate: `byok` flag AND `integrations.crypto.is_configured()`, else 501.
- Encryption: section 9.3.

### 6.7 Embeddings and the knowledge store

- `knowledge/embeddings.py`, `get_embedder()`: `EMBEDDINGS_BACKEND=fake` (tests, demo) or `http` (OpenAI-compatible `/v1/embeddings`, BGE-M3 per E31) with `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_MODEL`, `EMBEDDINGS_DIMENSION` (default 1024), `EMBEDDINGS_API_KEY`. Anything else → `None` (not configured).
- `knowledge/store.py`, `get_store(dimension)`: `KNOWLEDGE_VECTOR_STORE=pgvector` (default outside tests; table `knowledge_vec_1024`, HNSW `m=16`, `ef_construction=64`) or `json` (`KnowledgeVectorJSON`, local dev and tests only). Returns `None` when pgvector is missing.
- `knowledge/index.py`: `chunk_text`, `index_source(source_type, source_id)`, `request_index(...)` (queues `INDEX_JOB` via `jobs.enqueue`, never raises), `delete_source`. `knowledge/signals.py` indexes documents, room messages, transcripts and meeting summaries on save when `memory_search` is on, and deletes chunks and vectors on delete whatever the flag says.
- `knowledge/retrieve.py`: `allowed_chunks(user, org, model, rooms=None, source_types=None)` filters by what the user may read before `retrieve(...)` ranks (E16). Never rank first and filter later.
- `knowledge/prompting.py`: `sources_block(hits)` wraps sources in `<source>` tags as quoted data; `citations(hits)`.
- `manage.py index_knowledge --org <id> [--inline]` backfills an org.

### 6.8 Demo AI

- `brain/llm/demo_ai.py`: `enabled()` is `DEMO_MODE and DEMO_AI`. `reply(messages, tools)` returns labelled sample text, never touches the network, and proposes a `tasks.create` tool call when the person asks for a task and the tool is offered.
- `brain/llm/demo_handlers/`: one module per area with `handle(system, user, messages, tools)` returning a `ProviderResult` (build it with `brain.llm.demo_ai._result`) or `None`. `dispatch()` tries modules in module-name order before the built-in answers. Demo output must say it is demo output.
- The demo BYOK provider (`integrations.credentials.DEMO_PROVIDER = "demo"`) also answers through the demo model, and only in demo mode.

### 6.9 Buddies

- `buddies/chat.py`, `run_buddy_turn(user, org, chat, text, data, surface="buddy") -> (status, body)`. In order: buddy memory `before_turn` hook (commands answered without a model); credential or platform path (BYOK flag and crypto, `resolve_for_use`; or `direct.is_configured()` and `budget_decision`); `check_ai`; retrieval (`memory_search` flag, buddy sources); system prompt (`BUDDY_BASE`, buddy instructions, `templates_extra.context_for`, `memory_hooks.context`); offered tools (`ai_actions` flag, `actions.service.offered_tools`, plus external agent tools); provider call; usage recording; tool calls turned into proposals; `memory_hooks.after_turn`; assistant message saved. Returns 200 with `usage`, `citations`, `sources_state`, `proposals`, `proposal_errors`, `external_calls`.
- `buddies/router.py`: Flo (`flo_router` flag). `decide(user, org, text, room=None, chat=None)` picks a buddy by keywords or a model call; `flo_turn(...)` runs it and records `BuddyRoute` and `BuddyAnswer`.
- `buddies/quality.py`: `stats(org, user, days)` for the quality page (numbers only).
- `buddies/templates_extra.py`: specialist templates (Sales, Onboarding, Meeting, Customer), `install(org, key)`, `ensure_flo(org)`, `context_for(buddy, user, org)` (the viewer's own facts as quoted data).
- `buddies/seeds.py`: `seed_org(org)`, `seed_crew(org)`; `manage.py seed_buddies`; `BUDDY_SEED_ORG_SLUGS` (default `flolabs`).
- `buddies/services.py`: `visible_buddies`, `can_edit`, `clean_definition`, `holds_tool`, `can_decide_share`. A custom buddy can only use sources and tools its creator can access (Decision 34).
- Prompt-injection stance: retrieved sources and outside-agent output are wrapped as untrusted data (`_for_model` wraps `ROLE_EXTERNAL` messages in `<external_data trust="untrusted">`). Models never execute anything; they can only propose.

### 6.10 External agents and MCP

- FloBrain as an MCP server: `api/mcp` (`platform_api/mcp.py`), authenticated by PAT or MCP OAuth (`platform_api/oauth_mcp.py`: dynamic client registration, PKCE S256, resource binding, rotating refresh tokens). Write tools still go through approvals. Governance and the call log: `platform_api/mcp_hub.py` (`mcp_hub` flag, `mcp.manage`), `purge_mcp_logs` after 90 days.
- FloBrain as an MCP client: `platform_api/external_agents.py`. A host must be on both the owner's org allowlist and the install-wide `EXTERNAL_AGENT_ALLOWED_HOSTS`. The owner approves the exact tool list; a change needs approval again. Every call uses `platform_api.net`, re-checks the allowlist, the `external_agents` flag and `private_only` (always blocked there). Arguments obey the org's `pii_redaction`. A buddy only proposes a call; its person approves it. Output is untrusted text (Decision 48). See `docs/v2/features/MCP.md`.

---

## 7. Actions and approvals

### 7.1 The rule

Any write that leaves FloBrain, or any AI-initiated change, goes through an `ActionProposal` that the person approves (Decision 33, Decision 36, `GROWTH_PLAN.md` rules). Models only propose. Scheduled runs create approval requests and never write unattended (Decision 46).

### 7.2 Tool registry

`actions/registry.py`:

- `TOOLS`: key → `{"perm_key", "risk", "label", "description", "schema"}`. Risks: `READ = "read"`, `WRITE = "write"`, `EXTERNAL = "external"`. Built-in keys: `tasks.create`, `tasks.assign`, `tasks.update_status`, `rooms.post_message`, `meetings.create`, `email.draft`, `content.publish` (risk `external`), `reports.generate`.
- Provider function names cannot contain dots: `function_name("tasks.create") == "tasks__create"`, `tool_key_for()` reverses it. `provider_tools(keys)` builds OpenAI-style `tools`.
- `actions.service.sync_tool_definitions()` mirrors `TOOLS` into `ToolDefinition` rows (`requires_approval = risk != "read"`). Setting `ToolDefinition.enabled=False` turns a tool off.

### 7.3 Plugin tools

`actions/plugins.py`:

```python
register_tool(key, spec, *, check=check_fn, execute=execute_fn)
```

- Call it once from your app's `AppConfig.ready()` (see `datasets/apps.py` and `datasets/tools.py`). Guard against double registration with `handler(key) is None`.
- `spec` needs `perm_key`, `risk`, `label`, `description`, `schema`. Add `"flag": "<flag>"` so buddies are not offered the tool while that flag is off (`actions.service._flag_allows`).
- `check(user, org, args) -> str` returns the one-line summary for the approval card, or raises `actions.service.ActionDenied(code, details)` (`not_found`, `permission`, `not_available`, `invalid`).
- `execute(user, org, args) -> dict` runs only after approval. It must re-check its own target.
- Registered today by `datasets`, `einvoice`, `automations`, `integrations/write`, `platform_api/mcp_tools_extra.py`.

### 7.4 Lifecycle

`actions/service.py`:

1. `offered_tools(user, org, buddy)`: the buddy's `allowed_tools` that are enabled, whose flag is on, and that the user holds (`holds_tool`).
2. The model returns tool calls. `propose_from_calls(user, org, chat, buddy, calls, offered)` validates each against the JSON schema, runs `check()`, and creates an `ActionProposal` (`status=proposed`, `expires_at` = now + 24 hours). Errors are returned, not raised. Audited as `action.proposed`. Nothing executes here, whatever the tool's risk.
3. The person sees an approval card. `edit(proposal_id, user, org, edited_args)` re-validates edited arguments (audited `action.edited`, original arguments kept once).
4. `approve(proposal_id, user, org, edited_args=None)`: expired proposals become `expired`; otherwise the row is locked (`select_for_update`), `check()` runs again for the approver now, then `execute()` runs in a nested transaction. Outcomes: `executed` (audited `action.executed`, a "Done: ..." message is added to the thread), `failed` (audited `action.failed`, never re-run), or a denial (`not_found`, `permission`, `not_available`) that rolls back and leaves the proposal open (audited `action.denied`).
5. `reject(...)` → `rejected`, audited.

Only the person the proposal was made for can decide it; anyone else gets 404 (E39). Statuses: `proposed`, `approved`, `rejected`, `executed`, `failed`, `expired`.

---

## 8. Async work and scheduling

### 8.1 Job queue

`jobs/queue.py`, PostgreSQL only (E17, no Redis, no SQS, no Celery):

```python
from jobs.queue import enqueue, register

@register("myapp.do_thing")
def do_thing(payload): ...

result = enqueue("myapp.do_thing", {"id": str(obj.id)})
```

- `enqueue` runs the handler inline when `jobs_eager()` (always under tests; `JOBS_EAGER`, default `True` when `DEBUG` or testing). Otherwise it creates a `jobs.Job` row if `JOBS_WORKER_ENABLED=True`, or returns `{"ok": False, "reason": "unavailable"}` and creates nothing. Callers must handle "unavailable".
- Register handlers in a module imported from your `AppConfig.ready()` (see `agents/apps.py`, `pulse/apps.py`), or the worker will not know them.
- Worker: `python manage.py run_jobs` (`jobs/worker.py`). Claims one row with `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL, runs the handler outside any transaction, retries with backoff up to `MAX_ATTEMPTS = 5`, requeues rows stuck in `running` longer than `JOBS_STALE_SECONDS`. Stops cleanly on SIGTERM. Options: `--once`, `--max-jobs`, `--max-seconds`, `--poll-interval` (default `JOBS_POLL_SECONDS`), `--exit-when-idle`.
- Payloads are JSON. Pass ids, not objects or secrets.

### 8.2 Scheduled commands

From `awssupport.md` 3.11. In production each runs as a one-off ECS task (EventBridge Scheduler → ECS RunTask), never inside web tasks.

| Command | App | Cadence | Purpose |
|---|---|---|---|
| `tick_agents` | `agents` | every minute | Scheduled AI agents |
| `tick_webhooks` | `platform_api` | every minute | Webhook retries |
| `tick_content` | `content_studio` | every minute | Content Studio queue and scheduled posts |
| `tick_pulse` | `pulse` | every 5 minutes | Pulse alert rules |
| `tick_automations` | `automations` | every minute | Workflows, daily brief, nudges |
| `run_data_reports` | `datasets` | every hour | Sheet refresh and scheduled reports |
| `tick_bridges` | `bridges` | every minute | Mirrors notices to Slack and Teams DMs |
| `run_scheduled_evals` | `evals` | daily | Scheduled buddy evaluation runs |
| `tick_buddy_memory` | `buddy_memory` | daily | Expires buddy memories past retention |
| `purge_mcp_logs` | `platform_api` | daily | Deletes MCP call logs older than 90 days |
| `compliance_tick` | `compliance` | daily | Access review reminders, expired evidence packages |
| `tick_tasks` | `tasks` | every hour | "Due tomorrow" and "overdue" reminders; safe to run twice |
| `purge_exports` | `exports` | daily | Deletes expired org memory exports |
| `apply_retention` | `privacy` | daily | Deletes data past each org's retention policy, with vectors |

Also: `export_status` writes the public `status.json` (every minute, separate hosting, `awssupport.md` 3.14). Other commands: `run_jobs`, `create_org`, `seed_v2_demo`, `seed_demo`, `seed_buddies`, `index_knowledge`, `set_platform_admin`, `worker_token` (`--issue NAME --kind render|meeting_bot`, `--revoke ID`), `build_studio_demo_media`, `warmup` (V1 memory).

Write tick commands so they are safe to run twice and safe to run late.

### 8.3 Demo ticker

`demo/ticker.py`, started from `DemoConfig.ready()` when `DEMO_MODE=True`, not under tests, `DEMO_TICKS` not off, and not in `migrate`, `test`, `shell`, `run_jobs`, `seed_demo` and similar. Every `DEMO_TICK_SECONDS` (60, minimum 15) a daemon thread runs `tick_tasks`, `tick_agents`, `tick_webhooks`, `tick_content`, `tick_pulse`, `tick_automations`, `run_data_reports`, `tick_bridges`. On PostgreSQL an advisory lock keeps it to one process. If you add a tick command that the demo needs, add it to `COMMANDS`.

---

## 9. Cross-cutting helpers

### 9.1 Audit

```python
from organizations.services import audit
audit(actor, "thing.update", target=obj, payload={"before": ..., "after": ...}, request=request, org=org)
```

- `org` is required (taken from `request.org` or `target.org` when not passed; else `ValueError`).
- Records actor, optional impersonator, action, target type and id, payload, client IP (via `DRF_NUM_PROXIES`) and user agent.
- `AuditEvent` is append-only: `save()` refuses updates and `delete()` raises. Never delete audit rows (`RUNBOOK.md`).
- Audit every change to permissions, money, policy, members, approvals and anything that leaves FloBrain. Never put secrets in the payload.

### 9.2 Notifications

```python
from notifications.services import notify
notify(org, users, "access.granted", {"perm_key": key}, link="settings/access", push=False, push_title="")
```

Only active members of `org` receive it; per-type `NotificationPreference` mutes it. Web Push payloads carry no message text (`SECURITY_REVIEW.md`).

### 9.3 Encryption

- `integrations/crypto.py` (E20): AES-256-GCM, 96-bit random nonce, associated data `flobrain-credential:{id}:{org_id}` so a row copied to another record or org does not decrypt. `encrypt(secret, credential_id, org_id) -> bytes`, `decrypt(blob, credential_id, org_id, key_version)`, `is_configured()`, `current_key_version()`. Raises `CredentialCryptoError`; never falls back to a default key.
- Key: `CREDENTIALS_ENCRYPTION_KEY`, 64 hex characters, never all zeros. Version: `CREDENTIALS_KEY_VERSION` (default 1). `decrypt` refuses a row whose `key_version` differs from the current version, so changing the version makes old secrets unreadable until re-entered (`TECH_DEBT.md`).
- Used for BYOK keys, channel secrets (`channels/vault.py`, which also produces masked hints like `…abcd`), inbound automation hook secrets, social and connector OAuth tokens, Notion tokens, read-only database DSNs.
- `AES_MASTER_KEY` is separate. It is the V1 memory tier-3 key. Check `flobrain.E001` refuses a missing or all-zero key when `DEBUG=False` unless `ALLOW_INSECURE_AES_MASTER_KEY=1` (emergency only, E21). `flobrain.W001` warns on a short `SECRET_KEY`.
- `SECRET_KEY` signs JWTs; rotating it logs everyone out.

### 9.4 Outbound HTTP

Use `platform_api.net` for any URL that a customer, an org setting or a third party can influence:

- `check_url(url)`: `https` only, no credentials in the URL, port 443 or 8443, host name (not an IP literal), DNS resolved with a 5-second timeout, every address public (no private, loopback, link-local, multicast, reserved, site-local; IPv4-mapped IPv6 unwrapped).
- `fetch(method, url, body=b"", headers=None, timeout=10, max_bytes=4096) -> (status, body)` and `fetch_full(...) -> (status, headers, body)`: connect to the checked IP with the original host for SNI and certificate checks (DNS pinning), a 15-second whole-request deadline, a response size cap, and no redirects (3xx is returned as is). `post(url, body, headers)` returns the status.
- Raises `net.UnsafeURL` or `OSError`. Turn both into a clean error, never a 500.

Per-feature host allowlists on top of that:

| Setting | Feature |
|---|---|
| `BYOK_ALLOWED_HOSTS` | Customer AI keys (`integrations/credentials.py`, via `brain.llm.http.open_customer`) |
| `EXTERNAL_AGENT_ALLOWED_HOSTS` | Outside MCP servers (plus the owner's org allowlist) |
| `AI_SELF_HOSTED_HOSTS` | Hosts allowed for `private_only` orgs |
| `AI_ALLOW_PLAINTEXT_HOSTS` | In-cluster model hosts over plain `http` (sovereign only) |
| `EINVOICE_SIGNER_ALLOWED_HOSTS` | External e-invoice signers (`einvoice/transport.py`) |
| `FLOBRAIN_ODOO_ALLOWED_HOSTS` | Odoo write connector |
| `DATA_REGION_HOSTS`, `DATA_REGION_AI_HOSTS_<REGION>` | Data residency (`einvoice/residency.py`) |

Platform-configured hosts (`AI_DIRECT_BASE_URL`, embeddings, Stripe, LiveKit, ASR, the multimodal service) use `urllib` directly. New code that calls a URL from org data must use `net`.

### 9.5 Inbound webhook verification

Patterns in the code:

- HMAC-SHA256 over the raw body, compared with `hmac.compare_digest` (`integrations_hr/views.py`, header `X-Flobrain-Signature`, secret `HR_WEBHOOK_SECRET`; missing secret → 503).
- Timestamped signatures with a tolerance window: Stripe (`billing_v2/stripe.py` `verify`, `t=...,v1=...` over `"{t}." + body`, `STRIPE_WEBHOOK_TOLERANCE` 300 s); automation inbound hooks (`automations/views.py`, timestamp skew check, per-hook secret encrypted with `integrations.crypto`); Slack signing secret (`bridges/slack.py`). Outbound FloBrain webhooks are signed the same way (`platform_api/webhooks.sign`: `t=<ts>,v1=<hmac>`).
- Platform-specific: Teams Bot Framework JWTs (`bridges/teams.py`), WhatsApp and Telegram secrets (`channels/providers.py`), LiveKit webhook signed with the API secret.
- Idempotency: store the provider's event id or a hash and ignore repeats (`StripeEvent`, `channels.InboundEvent`, automation runs keyed `event_key=f"webhook:{sha256(timestamp + body)}"`).
- Limit the body size before parsing (automations answer 413), parse JSON only after the signature passes, and answer 202 for accepted async work.

For client retries on V2 POSTs, `core_v2/idempotency.py` offers `idempotency_key(request)`, `remember_response(...)` and `replay_response(...)` keyed on an `Idempotency-Key` header in the cache.

### 9.6 Rate limiting

DRF throttles and the `cache.add` / `cache.incr` counters all use Django's default cache. `settings.py` defines no `CACHES`, so it is LocMem: each process counts on its own and counts reset on restart. With several gunicorn workers or ECS tasks, limits are per process. A shared cache is needed in production before these limits can be trusted (see Known gaps). Set `DRF_NUM_PROXIES=1` behind the ALB or every client shares one IP.

### 9.7 File storage

- Content Studio, exports, privacy downloads, meeting recordings: `content_studio/storage.py`. `CONTENT_STORAGE=s3` with `CONTENT_S3_BUCKET` and `CONTENT_S3_REGION` (presigned URLs only, 5-minute downloads per `SECURITY_REVIEW.md`), `local` with `CONTENT_LOCAL_DIR` (HMAC-signed local URLs under `/api/v2/content/local/`), or empty → not configured. Keys are always built by the server.
- Document attachments: `docs_app/views.py` `storage_mode()`. Local disk only (`DOCS_FILE_STORAGE=local`, default in DEBUG, tests and demo; `DOCS_LOCAL_STORAGE_DIR`, default `media/docs`). On ECS it answers "not set up" (`TECH_DEBT.md` C1).
- Datasets: `DATASETS_DIR`. Voice notes: `VOICE_TMP_DIR`.

### 9.8 PII redaction

`platform_api/pii.py`. `PII_DETECTOR`: empty (none; the org setting cannot be turned on), `regex` (basic `RegexDetector`, default in demo), or a dotted class path. `OrgPolicy.pii_redaction` is `off`, `external_only` or `always`. Applied today to arguments sent to external agents (`redact_value`) and in buddy memory filters. `redact_for(org, text)` is available for other outbound paths.

---

## 10. Data and migrations

### 10.1 Model conventions

Follow what the V2 apps do (see `commissions/models.py`):

```python
id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="...")
created_at = models.DateTimeField(default=timezone.now)
updated_at = models.DateTimeField(auto_now=True)

class Meta:
    db_table = "<explicit_table_name>"
```

- UUID primary keys on all new tables (E7). Exception: `brain_chats` keeps its integer id.
- An `org` foreign key on every org-owned row. Every query filters by it.
- Explicit `db_table`.
- User references point at `"users.User"`. Use `SET_NULL` for "who did it" columns so deleting a person does not fail (the commissions review changed a `PROTECT` that caused a 500).
- Append-only tables (`AuditEvent`, `UsageEvent`, `AITrace`, `ProductEvent`) refuse updates.
- `AppConfig.default_auto_field` is `BigAutoField`; it only matters for tables without an explicit id.

### 10.2 Writing migrations

- Make them per app: `python manage.py makemigrations <app_label>`. Commit only your app's new files.
- Never edit or renumber a migration that is already merged, and never edit another app's migrations. Add a new one.
- Additive and reversible (`PLAN.md` section 0). New columns nullable or with a default.
- Keep data steps in their own migration, not in the same migration as schema changes. On PostgreSQL with existing rows, mixing them failed with "pending trigger events" (`REVIEW_COMPLETION.md`, `tasks/0003`, `marketplace/0003`, `marketplace/0004`).
- PostgreSQL-only SQL must check `schema_editor.connection.vendor` and skip on SQLite, and must not abort the migration when an extension is missing (copy `knowledge/migrations/0001_pgvector.py`).
- CI runs `makemigrations --check --dry-run`. A missing migration fails the build.

### 10.3 Running migrations

- Locally: `python manage.py migrate`.
- Production: one one-off ECS task with `python manage.py migrate --noinput`, then start or update the web service only after it exits 0. Never run `migrate` in every web task (E33, `awssupport.md` 3.5).
- Rollback: do not reverse migrations that drop data. Forward-fix or restore from RDS (`RUNBOOK.md`).

### 10.4 SQLite versus PostgreSQL

Tests and the demo run on SQLite. Production is PostgreSQL 15.17 on RDS. Code that behaves differently:

| Area | PostgreSQL | SQLite |
|---|---|---|
| Job claims (`jobs/worker.py`) | `FOR UPDATE SKIP LOCKED` | plain claim |
| `select_for_update()` (seats, approvals, many more) | real row locks | no-op |
| Search (`search/views.py`) | `SearchVector` full text | `icontains` |
| Vectors (`knowledge/store.py`) | pgvector, HNSW | `json` store only; `pgvector` store returns `None` |
| Demo ticker, render and bot workers | advisory locks | no lock |
| Evals runner | parallel workers | one at a time |

Run your app's tests on PostgreSQL too when you touch locking, search, JSON queries or migrations. The reviews ran every suite on both (`REVIEW_*.md`).

### 10.5 pgvector

`CREATE EXTENSION IF NOT EXISTS vector` is in `knowledge/migrations/0001_pgvector.py`. Supported dimension: 1024 (`SUPPORTED_PGVECTOR_DIMENSIONS`). After enabling on a server, check `SELECT extversion FROM pg_extension WHERE extname='vector'`; versions older than 0.8 filter after the HNSW scan and can return fewer than `k` hits (`TECH_DEBT.md`). The RDS instance is `db.t3.micro` (1 GB); move to a larger class before real retrieval load (`awssupport.md` 3.7).

---

## 11. Demo mode

### 11.1 Settings

- `DEMO_MODE=True` turns on demo sign-in, the demo org, the demo IdP and the ticker. Every demo endpoint (`api/v2/demo`, `demo/signin`, `demo/reset`, `demo/idp/sso`) answers 404 when it is off.
- `DEMO_AI` (default `True` when `DEMO_MODE` is on): the built-in demo model, no network, no key.
- In demo mode, `PII_DETECTOR` defaults to `regex`, content storage defaults to a temp folder, and doc attachments use local storage.
- Check `flobrain.W010` warns when `DEMO_MODE` is on without `DEBUG`.

**Never set `DEMO_MODE` in staging or production.** Anyone who can reach the API can sign in as the demo users. A demo environment must have its own database, bucket and secrets (`awssupport.md` 3.15).

### 11.2 Seed

- `demo/seed.py`: `reset()` wipes only the org with slug `demo` that is marked `settings["demo"] = True` and users with provider `demo`, then builds Nile Labs: owner, admin, lead, member (and a designer) with unusable passwords, teams, a project, tasks, time, rooms, documents, meetings, buddies, and more. `FLAGS` lists every flag turned on.
- `demo/extras/`: one module per area with `seed(org, users, now)`. `demo.extras.run_all` imports them in module-name order after the core demo is built. Digits sort before letters: `10_meetings`, `20_rooms`, `20_sso`, `30_tasks`, ..., `97_voice`, then `a1_mcp`, ..., `a8_pricing`. Name a new module so it runs after the data it needs (for example `a9_<area>.py`).
- `users` maps role keys (`owner`, `admin`, `lead`, `member`, `designer`) to `User` rows. Find rooms, teams and the project by name in `org`.
- Keep demo data clearly labelled ("demo", `example.com` / `demo.flobrain.example` addresses).
- `python manage.py seed_demo` builds it; the first demo sign-in also builds it; "Start the demo over" (`demo/reset`) rebuilds it at most once a minute.

### 11.3 Demo handlers

Add a `brain/llm/demo_handlers/<area>.py` with `handle(system, user, messages, tools)` when your feature's prompts need a believable demo answer. Recognize your prompt with a marker in the system text (the data buddy uses `[flo:data-sql]` and `[flo:data-chart]`). Return `None` for prompts that are not yours. Handlers run in module-name order, so a handler that matches too broadly hides later ones.

---

## 12. Testing

### 12.1 Layout

- Tests live in each app: `tests.py`, `test_*.py`, or a `tests/` package (`organizations/tests/`). About 128 test modules. `memory/manual_checks/` holds old manual scripts outside discovery (E15).
- Typical setup: create an `Organization` with `settings={"flags": {...}}`, `User`s with `password_hash=make_password(...)`, `OrgMembership`s with roles and `employment_status="active"`, then an `APIClient` with `HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}"` (see `commissions/tests.py`). Shared kits exist for bigger apps (`bridges/_testkit.py`, `channels/_testkit.py`).

### 12.2 Running

`/home/claude/runtests.sh` is a local helper on one machine, not part of the repo. The equivalent:

```bash
cd flobrain-core/backend
export DEBUG=True ALLOW_INSECURE_AES_MASTER_KEY=1 TEST_HANG_TIMEOUT=600
export SECRET_KEY='<any local string, 32+ chars>'

# SQLite
DB_ENGINE=sqlite python manage.py test --noinput

# PostgreSQL
DB_ENGINE=postgresql DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=flobrain_db DB_USER=flo_user DB_PASS='<local>' \
PGOPTIONS="-c lock_timeout=10000 -c statement_timeout=120000" \
python manage.py test --noinput

# Subsets
python manage.py test commissions
python manage.py test organizations.tests.test_matrix
python manage.py test buddies.tests.SomeTestCase.test_name
```

When `test` is in `sys.argv`, `settings.TESTING` is `True`: fast MD5 password hashing, `EMBEDDINGS_BACKEND=fake`, `KNOWLEDGE_VECTOR_STORE=json`, `CONTENT_STORAGE=local`, jobs run eagerly, `MULTIMODAL_SERVICE_TIMEOUT=2`, and the AES and demo-mode checks relax.

CI (`.github/workflows/django-backend-ci.yml`): Python 3.11, a `postgres:15` service, `DEBUG=False`, `MONGO_PORT=1` (closed), then `check`, `makemigrations --check --dry-run`, `migrate`, `test --noinput -v 2`, `spectacular`. It triggers on `flobrain-core/backend/**` for pushes and PRs to `main`.

### 12.3 The hang-safe runner

`TEST_RUNNER = "flobrain.test_runner.HangSafeDiscoverRunner"`:

- Arms `faulthandler.dump_traceback_later` (`TEST_HANG_TIMEOUT`, default 1200 s) before database setup, so a stuck run dumps every thread's stack and exits instead of hanging silently.
- Blocks outbound sockets: any `connect` to a host other than `127.0.0.1`, `::1` or `localhost` raises `OSError("Outbound network is blocked in tests: ...")`. `flobrain/test_network_guard.py` tests both.

Parallel: Django's `--parallel N` is available. The documented review runs used `--parallel 1` on PostgreSQL (`PROGRESS.md`); parallel runs are not documented as verified.

### 12.4 Mocking the network

Nothing may reach the network in tests or the demo. Mock at the boundary:

| Call | Patch |
|---|---|
| Customer URLs | `platform_api.net.fetch`, `fetch_full`, `post`, `resolve` |
| `direct` model calls | `urllib.request.urlopen`, or `brain.llm.direct.chat_complete` |
| BYOK calls | `brain.llm.http.open_customer` |
| Stripe | `billing_v2.stripe._post` |
| LiveKit, ASR | `meetings.livekit._api`, `meetings.asr.transcribe_file` |
| Jobs | `jobs.queue.enqueue` (when you need to assert queuing) |

Use `override_settings(...)` for env-driven settings, not `os.environ`.

### 12.5 What a feature's tests must cover

- Flag off → 501 (and the per-member flag off for one person, `commissions/tests.py`).
- Permissions: each role allowed and denied; an outsider and an inactive member; 404 for objects outside scope; owner-only keys refused for admins and platform admins.
- Validation: bad input → 400, including edge values (`NaN`, `Infinity`, negative, too long, newlines).
- Org isolation: a member of another org cannot read or change anything.
- Security: secrets never in responses, logs or audit payloads; only masked hints; signatures and timestamps checked on hooks; SSRF guard (`net` refuses private hosts).
- Approval gating: an AI-proposed write creates a proposal and changes nothing until approved; approval re-checks access; a lost permission leaves the proposal open.
- Audit rows for every change, with before and after where money or access changes.
- V1 unchanged where you touched shared code (V1 shape and status tests, best-effort telemetry, E28).
- Demo seed runs (`demo/tests.py`, `platform_api/test_demo_seed.py`) and the demo handler answers.

---

## 13. Deploy and environments

### 13.1 Shape

From `awssupport.md` (read it for the full checklist; nothing there has been applied to AWS yet):

- Website on Vercel. API at `api.flobrain.ai` behind an ALB on ECS Fargate (`flolabs-dev-django-service`), today running `runserver`. RDS PostgreSQL 15.17 (`db.t3.micro`). Private S3 bucket. The multimodal service runs in a second AWS account.
- Planned for V2: staging first; secrets in Secrets Manager; `/healthz` health check then strict `ALLOWED_HOSTS`; gunicorn (`gunicorn flobrain.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60`); migrations as a one-off task; one `run_jobs` worker service with `JOBS_WORKER_ENABLED=True` on both services; the scheduled commands of section 8.2; pgvector and a larger RDS class; the meetings stack (`awssupport.md` 3.12); static hosting for `status.json`.
- The deploy workflow `.github/workflows/backend-deploy.yml` exists and is disabled (`if: false`).
- `ProductionEnvBootTests` (`organizations/tests/test_production_env.py`) boots the app with only today's production env names. It proves that `AES_MASTER_KEY` and `CORS_ALLOWED_ORIGINS` are the only boot blockers.

### 13.2 Environment variables by group

Names only. Values live in Secrets Manager or the task definition.

| Group | Names |
|---|---|
| Core | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL`, `DRF_NUM_PROXIES`, `FRONTEND_BASE_URL`, `PUBLIC_API_BASE_URL`, `DEFAULT_FROM_EMAIL` |
| Database | `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`, `SQLITE_PATH` |
| Keys | `AES_MASTER_KEY`, `ALLOW_INSECURE_AES_MASTER_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, `CREDENTIALS_KEY_VERSION`, `CERTIFICATE_SIGNING_KEY`, `CERTIFICATE_PREVIOUS_PUBLIC_KEYS` |
| Mail | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SALES_EMAIL` |
| V1 AI | `MULTIMODAL_SERVICE_URL`, `MULTIMODAL_API_KEY`, `MULTIMODAL_SERVICE_TIMEOUT`, `MONGO_HOST`, `MONGO_PORT`, `S3_VAULT_BUCKET` |
| V2 AI | `AI_PROVIDER_BACKEND`, `AI_DIRECT_BASE_URL`, `AI_DIRECT_API_KEY`, `AI_DIRECT_MODEL_ALLOWLIST`, `AI_DIRECT_DEFAULT_MODEL`, `AI_DIRECT_TIMEOUT`, `AI_DIRECT_PROVIDER`, `AI_SELF_HOSTED_HOSTS`, `BYOK_ALLOWED_HOSTS`, `BYOK_CHECK_TIMEOUT`, `PII_DETECTOR`, `EXTERNAL_AGENT_ALLOWED_HOSTS` |
| Embeddings and knowledge | `EMBEDDINGS_BACKEND`, `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_API_KEY`, `EMBEDDINGS_MODEL`, `EMBEDDINGS_DIMENSION`, `EMBEDDINGS_TIMEOUT`, `KNOWLEDGE_VECTOR_STORE`, `KNOWLEDGE_CHUNK_CHARS`, `KNOWLEDGE_CHUNK_OVERLAP`, `KNOWLEDGE_ASK_TOP_K`, `KNOWLEDGE_CONTEXT_CHARS` |
| Jobs | `JOBS_EAGER`, `JOBS_WORKER_ENABLED`, `JOBS_POLL_SECONDS`, `JOBS_STALE_SECONDS` |
| Storage | `CONTENT_STORAGE`, `CONTENT_S3_BUCKET`, `CONTENT_S3_REGION`, `CONTENT_LOCAL_DIR`, `DOCS_FILE_STORAGE`, `DOCS_LOCAL_STORAGE_DIR` |
| Meetings | `LIVEKIT_URL`, `LIVEKIT_API_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ASR_BACKEND`, `ASR_BASE_URL`, `ASR_MODEL`, `ASR_API_KEY`, `ASR_TIMEOUT`, `MEETING_BOT_VENDOR`, `MEETING_BOT_API_KEY`, `MEETING_BOT_MAX_MINUTES`, `MEETING_UPLOAD_MAX_MB` |
| Billing | `BILLING_ENFORCE_ENTITLEMENTS`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_TOLERANCE`, `STRIPE_SECRET_KEY`, `STRIPE_PRICE_<PLAN>_<MONTH or YEAR>` |
| Webhooks and integrations | `HR_WEBHOOK_SECRET`, `FLOBRAIN_SLACK_CLIENT_ID`, `FLOBRAIN_SLACK_CLIENT_SECRET`, `FLOBRAIN_SLACK_SIGNING_SECRET`, `FLOBRAIN_TEAMS_APP_ID`, `FLOBRAIN_TEAMS_APP_SECRET`, `FLOBRAIN_TEAMS_TENANT_ID`, `FLOBRAIN_OAUTH_<PROVIDER>_CLIENT_ID`, `FLOBRAIN_OAUTH_<PROVIDER>_CLIENT_SECRET`, `FLOBRAIN_ODOO_ALLOWED_HOSTS`, `SOCIAL_<PLATFORM>_CLIENT_ID`, `SOCIAL_<PLATFORM>_CLIENT_SECRET`, `TTS_PROVIDER` |
| E-invoicing and residency | `EINVOICE_SIGNER_ALLOWED_HOSTS`, `EINVOICE_SIGNER_CLIENT_CERT`, `EINVOICE_SIGNER_CLIENT_KEY`, `EINVOICE_SIGNER_CA_FILE`, `DATA_REGION_DEPLOYMENT`, `DATA_REGION_DATABASE`, `DATA_REGION_FILES`, `DATA_REGION_HOSTS`, `DATA_REGION_AI_HOSTS_<REGION>` (more in `features/EINVOICE.md`) |
| Web Push | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` |
| Tunables | `FLOBRAIN_V2_*` (the `FLOBRAIN_V2` dict), `FLOBRAIN_V2_USER_THROTTLE`, `FLOBRAIN_V2_ANON_THROTTLE`, `PUBLIC_API_RATE`, `PUBLIC_API_USER_RATE`, `EXPORT_*`, `CONTENT_*` limits, `AGENT_MAX_RUNS_PER_HOUR`, `TRANSLATION_MAX_PER_REQUEST` |
| Demo and tests | `DEMO_MODE`, `DEMO_AI`, `DEMO_TICKS`, `DEMO_TICK_SECONDS`, `TEST_HANG_TIMEOUT`, `DJANGO_TESTING` |

### 13.3 Never in production

| Setting | Why |
|---|---|
| `DEMO_MODE` (and so `DEMO_AI`) | Anyone can sign in as demo users |
| `DEBUG=True` | Django debug pages; also makes jobs eager and doc storage local |
| `CORS_ALLOW_ALL=True` | Any origin can call the API; rollout escape hatch only |
| `ALLOW_INSECURE_AES_MASTER_KEY=1` | Emergency only (E21) |
| `AI_FORCE_PRIVATE_ONLY`, `AI_ALLOW_PLAINTEXT_HOSTS` | Sovereign installs only (`awssupport.md` 3.13) |
| `EMBEDDINGS_BACKEND=fake`, `KNOWLEDGE_VECTOR_STORE=json` | Test and local stores |
| `SOCIAL_SANDBOX_ENABLED=True` | Local test social connector |
| `EINVOICE_SIGNER_ALLOW_PRIVATE=True` | Self-hosted installs only |
| `JOBS_EAGER=True` | Runs jobs inside the request (E17) |
| `CONTENT_STORAGE=local`, `DOCS_FILE_STORAGE=local` on ECS | Task disk is not durable |
| `BILLING_ENFORCE_ENTITLEMENTS=True` before plans exist | Would lock orgs out of features |
| An all-zero `CREDENTIALS_ENCRYPTION_KEY` or `AES_MASTER_KEY` | Refused or insecure |

---

## 14. How to add a feature

### 14.1 Checklist

1. **Decide.** Find or add the spec decision (`DECISIONS.md`) and any open question. Pick a flag name, permission keys, and which roles hold them.
2. **Scaffold the app.** `python manage.py startapp <app>`; add an `AppConfig` with `default_auto_field = "django.db.models.BigAutoField"`, `name`, `verbose_name`; add `"<app>.apps.<Name>Config"` to the end of `INSTALLED_APPS`.
3. **Shared files, additive only.** Add keys to `PERMISSION_CATALOG` (and `_MEMBER_DEFAULTS` if members get them); add the flag to `KNOWN_FLAGS` (`organizations/views_access_me.py`) and to `FLAGS` in `demo/seed.py`; add one `path("", include("<app>.urls"))` line to `flobrain/urls_v2.py`. Append; do not reorder or reformat.
4. **Models.** UUID PK, `org` FK, timestamps, explicit `db_table`. `python manage.py makemigrations <app>`.
5. **Views.** Subclass `V2APIView`. Order: org 404, flag 501, permission 403, object scope 404, validation 400, policy 409. Audit every change. Return masked hints, never secrets. Add `@extend_schema(summary=...)`.
6. **Side effects.** Outbound calls through `platform_api.net` plus an allowlist. AI calls through `DirectProvider`, `check_ai`, `budget_decision`, `record_v2_provider_event`. External writes as a plugin tool with `register_tool` and `"flag"` in the spec. Slow work through `jobs.enqueue`, registered in `ready()`. Scheduled work as a `tick_<app>` management command.
7. **Tests.** Section 12.5. Run on SQLite and PostgreSQL. `makemigrations --check`.
8. **Demo.** A `demo/extras/<order>_<app>.py` with `seed(org, users, now)`; a `brain/llm/demo_handlers/<app>.py` if it calls a model; add any tick command to `demo/ticker.py` `COMMANDS`.
9. **Docs.** `docs/v2/features/<AREA>.md` (flags, permissions, endpoints, limits). A `CHANGELOG.md` entry (newest first: what changed, flags, migrations, new packages, V1 behaviour). New env, secrets, scheduled commands or public paths → `awssupport.md` (and `INFRA_CHANGES.md`). Shortcuts → `TECH_DEBT.md`.
10. **Frontend.** Expose state through `me/access` flags and permissions; see [`FRONTEND_GUIDE.md`](FRONTEND_GUIDE.md).

### 14.2 Minimal example: kudos

A made-up feature: members send kudos to each other; admins can delete any. Flag `kudos`, keys `kudos.send` (members) and `kudos.manage` (admins).

`kudos/apps.py`:

```python
from django.apps import AppConfig


class KudosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kudos"
    verbose_name = "Kudos"
```

`flobrain/settings.py` (append to `INSTALLED_APPS`): `"kudos.apps.KudosConfig",`

`organizations/permissions/registry.py` (append):

```python
    "kudos.send": {"label": "Send kudos to a colleague", "matrix": "org"},
    "kudos.manage": {"label": "Remove any kudos", "matrix": "org"},
```

and `"kudos.send"` in `_MEMBER_DEFAULTS`. Add `"kudos"` to `KNOWN_FLAGS` and to `demo/seed.py` `FLAGS`.

`kudos/models.py`:

```python
import uuid

from django.db import models
from django.utils import timezone


class Kudo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="kudos")
    sender = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    recipient = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="kudos_received")
    message = models.CharField(max_length=280)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "kudos"
        indexes = [models.Index(fields=["org", "recipient"], name="kudos_org_recipient")]
```

`kudos/views.py`:

```python
import uuid

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from kudos.models import Kudo
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services import audit

FLAG = "kudos"
MAX_MESSAGE = 280


def _gate(request, org_id, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Kudos are not enabled"}, status=501)
    if perm and not can(request.user, perm, org):
        return org, Response({"error": "permission_denied", "details": f"Missing permission: {perm}"}, status=403)
    return org, None


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None  # a malformed id must be a 400, not a 500 from the UUID field lookup


def _payload(k):
    return {
        "id": str(k.id),
        "sender": str(k.sender_id) if k.sender_id else None,
        "recipient": str(k.recipient_id),
        "message": k.message,
        "created_at": k.created_at.isoformat(),
    }


class KudoListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Kudos I sent or received")
    def get(self, request, org_id):
        org, error = _gate(request, org_id)
        if error:
            return error
        qs = Kudo.objects.filter(org=org, recipient=request.user).order_by("-created_at")[:100]
        return Response([_payload(k) for k in qs])

    @extend_schema(summary="Send kudos")
    def post(self, request, org_id):
        org, error = _gate(request, org_id, perm="kudos.send")
        if error:
            return error
        body = request.data if isinstance(request.data, dict) else {}
        message = str(body.get("message") or "").strip()
        if not message or len(message) > MAX_MESSAGE:
            return Response({"error": "invalid", "details": {"message": f"1 to {MAX_MESSAGE} characters"}}, status=400)
        recipient_id = _uuid(body.get("recipient"))
        recipient = None
        if recipient_id is not None:
            recipient = OrgMembership.objects.filter(
                org=org, user_id=recipient_id, employment_status=OrgMembership.STATUS_ACTIVE
            ).first()
        if recipient is None or recipient.user_id == request.user.id:
            return Response({"error": "invalid", "details": {"recipient": "Pick an active colleague"}}, status=400)
        kudo = Kudo.objects.create(org=org, sender=request.user, recipient=recipient.user, message=message)
        audit(request.user, "kudos.send", target=kudo, payload={"recipient": str(recipient.user_id)}, request=request, org=org)
        return Response(_payload(kudo), status=201)


class KudoDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Remove kudos")
    def delete(self, request, org_id, kudo_id):
        org, error = _gate(request, org_id)
        if error:
            return error
        kudo = Kudo.objects.filter(org=org, pk=kudo_id).first()
        if kudo is None or not (kudo.sender_id == request.user.id or can(request.user, "kudos.manage", org)):
            return Response({"error": "not_found"}, status=404)
        audit(request.user, "kudos.delete", target=kudo, payload={"recipient": str(kudo.recipient_id)}, request=request, org=org)
        kudo.delete()
        return Response(status=204)
```

Ids from the request body are parsed with `_uuid` before any lookup (same helper as `commissions/views.py`): filtering a `UUIDField` with a malformed string raises inside Django and would become a 500.

`kudos/urls.py`:

```python
from django.urls import path

from kudos import views as v

urlpatterns = [
    path("orgs/<uuid:org_id>/kudos", v.KudoListView.as_view(), name="v2-kudos"),
    path("orgs/<uuid:org_id>/kudos/<uuid:kudo_id>", v.KudoDetailView.as_view(), name="v2-kudo"),
]
```

`flobrain/urls_v2.py` (append): `path("", include("kudos.urls")),`

`kudos/tests.py`:

```python
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from kudos.models import Kudo
from organizations.models import AuditEvent, OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class KudosTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="K", slug="k-org", settings={"flags": {"kudos": True}})
        self.other = Organization.objects.create(name="O", slug="o-org", settings={"flags": {"kudos": True}})
        self.u = {}
        for name, role, org in (("admin", "admin", self.org), ("ana", "member", self.org), ("ben", "member", self.org), ("eve", "member", self.other)):
            user = User.objects.create(email=f"{name}@k.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status="active")
            self.u[name] = user
        self.base = f"/api/v2/orgs/{self.org.id}/kudos"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.u[name].id))}")
        return c

    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {}}
        self.org.save()
        self.assertEqual(self._as("ana").get(self.base).status_code, 501)

    def test_send_validate_and_audit(self):
        ana = self._as("ana")
        self.assertEqual(ana.post(self.base, {"recipient": str(self.u["ben"].id), "message": ""}, format="json").status_code, 400)
        self.assertEqual(ana.post(self.base, {"recipient": str(self.u["ana"].id), "message": "me"}, format="json").status_code, 400)
        self.assertEqual(ana.post(self.base, {"recipient": str(self.u["eve"].id), "message": "hi"}, format="json").status_code, 400)
        r = ana.post(self.base, {"recipient": str(self.u["ben"].id), "message": "Great demo"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="kudos.send").exists())

    def test_other_org_and_delete_scope(self):
        kudo = Kudo.objects.create(org=self.org, sender=self.u["ana"], recipient=self.u["ben"], message="x")
        self.assertEqual(self._as("eve").get(self.base).status_code, 403)  # not a member of this org
        self.assertEqual(self._as("ben").delete(f"{self.base}/{kudo.id}").status_code, 404)
        self.assertEqual(self._as("admin").delete(f"{self.base}/{kudo.id}").status_code, 204)
```

`demo/extras/a9_kudos.py`:

```python
def seed(org, users, now):
    from kudos.models import Kudo

    Kudo.objects.create(org=org, sender=users["lead"], recipient=users["member"], message="Thanks for fixing the login timeout (demo)")
```

Then: `python manage.py makemigrations kudos`, run the tests on both databases, write `docs/v2/features/KUDOS.md`, add a `CHANGELOG.md` entry ("New app `kudos`, flag `kudos`, keys `kudos.send`, `kudos.manage`, migration `kudos/0001`. V1 behaviour: unchanged.").

---

## 15. Rules

### Do

- Keep V1 paths, request and response shapes, and status codes unchanged. Any deliberate V1 change goes in `CHANGELOG.md`.
- Subclass `V2APIView` (or `V2PublicAPIView` for signed-out endpoints) for every V2 view.
- Filter every query by `org`. Resolve objects with `org=org` in the same lookup (`get_object_or_404(Model, pk=..., org=org)`).
- Check in this order: flag (501), permission (403), object scope (404 when the object must stay hidden).
- Pass the narrowest scope to `can()` (team or project when you have it).
- Re-check access at execution time (approvals, scheduled runs, jobs): permissions can change between request and run.
- Send every AI-initiated write and every write outside FloBrain through an `ActionProposal` approval.
- Call `check_ai` before every model call, `budget_decision` before every platform-key call, and record usage with `record_v2_provider_event`.
- Wrap retrieved content and outside-agent output as quoted, untrusted data in prompts.
- Audit every change that matters (access, money, policy, members, approvals, external effects).
- Encrypt stored secrets with `integrations.crypto`. Return only masked hints (`last4`, `…abcd`).
- Use `platform_api.net` plus a host allowlist for URLs that come from org data.
- Verify inbound hooks with a constant-time signature check, a timestamp window where the provider supports it, and an idempotency key.
- Answer 501 when a feature is off or a dependency is not configured, so nothing half-works.
- Make shared-file edits additive: append to `INSTALLED_APPS`, `urls_v2.py`, `PERMISSION_CATALOG`, `KNOWN_FLAGS`, `demo/seed.py` `FLAGS`; do not reorder, rename or reformat them.
- Make tick commands and job handlers idempotent.
- Keep the demo working without network for your feature.

### Don't

- Don't change global `REST_FRAMEWORK` defaults (V1 depends on them, E4).
- Don't put secrets, tokens, keys or passwords in code, fixtures, logs, audit payloads, error details or API responses. Env var names are fine; values are not.
- Don't send org content to the multimodal service (`multimodal_legacy`), and don't fall back to it or to the platform key when `direct` or a customer key fails.
- Don't execute model tool calls directly.
- Don't rank vectors before filtering by what the user may read.
- Don't use `requests` or `urllib` directly for customer-supplied URLs, and don't follow redirects with customer credentials.
- Don't run `migrate` on web start in production, edit merged migrations, or edit another app's migrations.
- Don't mix schema and data changes in one migration.
- Don't return 403 where it would reveal that a hidden object exists; use 404.
- Don't let owners or admins read DMs or private groups they are not in (E37). Use `rooms.services.accessible_rooms` for every list, search and retrieval path.
- Don't add GET endpoints with side effects without checking `console.impersonation.is_impersonated` (impersonation is read-only).
- Don't delete `AuditEvent` rows, ever.
- Don't enable `DEMO_MODE`, `CORS_ALLOW_ALL` or the other settings in section 13.3 outside local or demo environments.
- Don't add Redis, SQS or Celery as a queue (E17).

---

## 16. Known gaps and tech debt

Backend items found while writing this guide, plus pointers into `TECH_DEBT.md`. Verify before relying on any of them.

**Infrastructure and config**

- No `CACHES` setting: throttles, `cache.add` counters, idempotency replay and the Pulse health cache are per-process LocMem. Limits multiply with workers and reset on restart. Production needs a shared cache; Redis is only an unapproved proposal for Channels (`INFRA_CHANGES.md`), so this is undecided.
- `FLOBRAIN_V2["AUTH_RATE"]` (`10/min`) and `FLOBRAIN_V2["UPLOAD_RATE"]` are defined but not read anywhere. V2 sign-in uses `V2AnonThrottle` (60/min per IP).
- `docker-compose.yml` uses `postgres:15` without pgvector, starts Mongo and Redis that V2 does not use, and requires a `.env` file.
- CI uses `postgres:15` without pgvector, so pgvector paths are not exercised in CI.
- `Dockerfile` still runs `runserver` (E26).
- Several settings are read with `getattr(settings, ...)` but not defined in `settings.py` (for example `DOCS_FILE_STORAGE`, `DOCS_LOCAL_STORAGE_DIR`, `DATASETS_*`, `BRIDGES_LIMITS`, `DEMO_TICK_SECONDS`), so setting them as env vars has no effect unless `settings.py` reads them. Not verified case by case; `run-demo.sh` exports `DOCS_FILE_STORAGE=local`, which the code may not see (demo mode makes doc storage local anyway).
- `create_org --all-features` turns on only the first 25 flags (`FEATURES` in `organizations/management/commands/create_org.py`); growth and market-round flags (`automations` to `workspace_pricing`) stay off.
- `demo/seed.py` `FLAGS` contains `privacy_center`, which is not in `KNOWN_FLAGS` and has no effect.
- The `cockpit` flag has no backend check.

**API conventions**

- E10 says error codes are "a fixed enum in code"; there is no such enum. Codes are free strings per view.
- Many list endpoints return plain arrays or ad hoc `{"results": ...}` without counts; only some use `V2PageNumberPagination`.
- `PLAN.md` asks for DRF serializers in new V2 code; many newer views parse `request.data` by hand.
- `IsActiveOrgMember` still accepts an `X-Org-Id` header as a fallback, despite Decision 51 (path-based org).
- The HR intake webhook (`integrations_hr/views.py`) uses a plain `APIView`, has no timestamp or replay protection, answers 503 (not 501) when its secret is unset, and defaults to org slug `flolabs` when none is sent.
- Status codes for "not configured" are mixed: 501 in most V2 features, 503 for HR intake and the realtime ticket (E36 notes the realtime case).

**Permissions**

- `PermissionGrant.SCOPE_ROOM` exists but `can()` ignores room-scoped grants.
- `_MEMBER_DEFAULTS` lists `chat.use` twice (harmless).
- Leads cannot grant permissions to their own team (`TECH_DEBT.md` C5).
- Support sessions can still read group rooms (`TECH_DEBT.md` C8, Q40, Q42).

**AI**

- Only one encryption key version at a time; there is no keyring for `CREDENTIALS_ENCRYPTION_KEY` rotation (`TECH_DEBT.md`).
- `ToolDefinition.requires_approval` is stored but not used to skip approval: every tool call, including `read` risk tools, becomes a proposal in `propose_from_calls`. Decision 33 allows read-only actions on the user's own data without approval; that path is not built for buddies.
- PII redaction is applied to external-agent arguments and buddy memory, not to `direct` or BYOK model calls.
- Platform `direct` calls use `urllib.request.urlopen`, which follows redirects; only BYOK calls use the no-redirect opener.
- Budget spend is computed row by row; the cap is soft (`TECH_DEBT.md`).
- Room AI threads do not offer tools yet; knowledge ask and translation do not take a customer key (`TECH_DEBT.md`).

**Stale or conflicting docs**

- `TECH_DEBT.md` says "SAML 2.0 is not built" and "`private_only` does not disable external keys yet (no `OrgPolicy` model)". The code has `sso/saml.py`, `api/v2/sso/saml/acs`, `OrgPolicy` and `brain.llm.policy.check_ai` for BYOK. Those lines look outdated.
- `PLAN.md` names the docs app `docs/`; the code uses `docs_app`. `PLAN.md` lists `billing/`; the code uses `billing_v2`.
- `DECISIONS.md` E33 and `awssupport.md` 3.5 agree on one-off migration tasks, but `docker-compose.yml` migrates on start (local only, acceptable).
- `awssupport.md` 3.11 lists fourteen scheduled commands; `export_status` (3.14) is scheduled separately.

**Testing**

- Parallel test runs (`--parallel N`) are not documented as verified; reviews used `--parallel 1` on PostgreSQL.
- Total test count is not stated here; `awssupport.md` reports 757 passing on SQLite and PostgreSQL 16 as of the 2026-10-21 completion entry, before the growth and market rounds.

See `TECH_DEBT.md` for the full list (Content Studio, meetings, privacy, SSO and SCIM limits, Pulse, integrations, the still-open V1 items D1 to D12 and C1 to C12).
