# FloBrain V2: Discovery Audit

Date: 2026-10-20. Phase -1 (Discovery). No code was changed to produce this document.

Inputs: the master prompt `docs/v2/FLOBRAIN_V2_CURSOR_PROMPT.md` ("the spec"), the backend report `../mohamed.md` (outside the repo, Arabic, same date; "the report"), and the code at the working copy (branch `moodchanger_health_buddy_in_tembletes`, 2 frontend-only commits ahead of `origin/main` at `7dbedb2`).

Rule applied: **where the code differs from the spec or the report, the code wins**, and the difference is listed in Section 3.

All paths are relative to the repository root `FloBrain/` unless stated.

## How this was verified

Commands run (read-only, against the local SQLite database and a throwaway test database):

| Command (in `flobrain-core/backend`) | Result |
|---|---|
| `python manage.py showmigrations` | All applied except `model_registry 0001_initial` (unapplied in the local `db.sqlite3`) |
| `python manage.py check` | `System check identified no issues` |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| `python manage.py spectacular --file <tmp>` | 23 paths, **21 unique errors** ("unable to guess serializer"), 6 operationId collisions |
| `python manage.py test users model_registry memory.tests brain dashboard contact` | **22 tests, all pass** (0.19 s) |

Local interpreter: `.venv` is **Python 3.14.3** with only the core packages (Django 5.2.17, DRF 3.18.0, drf-spectacular 0.30.0, PyJWT 2.13.0, simplejwt 5.5.1, pymongo 4.18.0). The Docker image uses Python 3.11. chromadb, boto3, celery, tiktoken and the rest of `requirements.txt` are not installed locally, so the memory tier modules were read, not executed.

Not verifiable from this repository: the multimodal service, the CloudFormation stacks, the ECS task definition, production data, and production environment variables. Those items are in `OPEN_QUESTIONS.md`.

---

## 1. Repository map

### 1.1 What V2 builds on

| Path | What it is |
|---|---|
| `flobrain-core/backend/` | **The Django backend (source of truth).** Project `flobrain`, apps `users`, `brain`, `memory`, `model_registry`, `dashboard`, `contact` |
| `flobrain-website/` | **The Next.js frontend** (www.flobrain.ai, deployed to Vercel) |
| `docs/` | Docs; `docs/v2/` holds the spec and these Discovery documents |
| `.github/workflows/` | CI for `flobrain-cloud` and `flobrain-website`; Vercel deploy for the website |

### 1.2 Present but not part of V2

| Path | What it is | V2 action |
|---|---|---|
| `flobrain-core/core/`, `flobrain-core/manage.py`, `flobrain-core/requirements.txt` | A second, minimal Django project (`core.settings`, a `/health/` URL, empty views). `flobrain-core/README.md` still documents running it on port 8001 | Ignore |
| `flobrain-core/api/` | Empty Django app stub (only `migrations/` and `__init__.py`) | Ignore |
| `flobrain-core/workflow-db/` | Standalone Mongo 7 compose with init scripts (its `01-init-collections.js` has a missing comma, a syntax error) | Ignore |
| `flobrain-core/backend/01-init-collections.js`, `02-indexes.js`, `03-seed.js` | Copies of the Mongo init scripts; **not mounted** by the backend compose | Ignore |
| `flobrain-cloud/` | FastAPI app "Caipo Backend": `GET /`, `POST /api/v1/chat/`, `POST /api/v1/audio/transcribe`, no auth, CORS `*`. **It is not the multimodal service** that Django calls. Has tracked `__pycache__/*.pyc` files | Ignore |
| `flobrain-hal/`, `flobrain-robotics/` | README only | Out of scope |
| `legacy/`, `scripts/`, `types/chat.ts`, `.pio/`, root `package-lock.json`, `project.treef` | Archived prototypes, AV helper scripts, PlatformIO artifacts, an empty lockfile | Ignore |
| `docs/architecture/CLOUD_VS_BRAIN.md`, `docs/onboarding/GETTING_STARTED.md`, `docs/ENGINEERING_HANDBOOK.md` | Describe FastAPI/CAIPO as the active backend. **Outdated** | Do not follow |

Sibling folders `../test/` and `../clear/` (outside the repo) contain copies of the repo and are ignored.

### 1.3 Branches

`origin/main` is the live integration branch (last merge #245, 2026-09-23). `origin/development`, which `CONTRIBUTING.md` and `RELEASING.md` name as the integration branch, was last updated 2026-01-11 and is 390 commits behind `main`. Decision E2: V2 PRs target `main`.

---

## 2. Backend (`flobrain-core/backend`)

### 2.1 Settings (`flobrain/settings.py`)

- `.env` is loaded from `BASE_DIR / ".env"` (the backend folder), not the current directory.
- `SECRET_KEY` defaults to `"django-insecure-local-development-only"`. The local `.env` value is 21 bytes; PyJWT warns that HS256 keys should be at least 32 bytes.
- `DEBUG` is true only for the exact string `"True"`.
- `ALLOWED_HOSTS = ["0.0.0.0", "127.0.0.1", "localhost"] + env ALLOWED_HOSTS`. Setting `ALLOWED_HOSTS="*"` in env works (the spec says production runs that way).
- `INSTALLED_APPS`: Django admin/auth/contenttypes/sessions/messages/staticfiles, `corsheaders`, `rest_framework`, `drf_spectacular`, `rest_framework.authtoken` (installed, its table exists, never used), then the six apps.
- Middleware order: CORS → Security → Session → Common → CSRF → Authentication → Messages → XFrame.
- `CORS_ALLOW_ALL_ORIGINS = True` (D4).
- `REST_FRAMEWORK`: default authentication Token, Basic, Session; JSON renderer only; `drf_spectacular` AutoSchema. **No** `NUM_PROXIES`, default permission, pagination, throttle rates or exception handler.
- `AUTH_PASSWORD_VALIDATORS` lists the four Django validators, but **no view calls them**; the only password rule enforced is `min_length=8` in the serializers.
- No `AUTH_USER_MODEL`, `CACHES` (so LocMem), `CELERY_*`, `LOGGING`, `STATIC_ROOT`, or security headers settings (`SECURE_PROXY_SSL_HEADER`, HSTS, secure cookies).
- `LANGUAGE_CODE = "en-us"`, `TIME_ZONE = "UTC"`, `USE_TZ = True`.
- `MULTIMODAL_SERVICE_URL` default `http://35.153.90.219:8000` (plain HTTP, public IP), `MULTIMODAL_API_KEY` default empty, `MULTIMODAL_SERVICE_TIMEOUT` default 60.

### 2.2 Environment variables actually read by the backend

| Variable | Read in | Default |
|---|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | `flobrain/settings.py` | see 2.1 |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT` | `flobrain/settings.py` | `postgresql`, `flobrain_db`, `flo_user`, `flo_password`, `localhost`, `5432` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SALES_EMAIL` | `flobrain/settings.py` | empty, `465` (SSL on, TLS off), empty |
| `MULTIMODAL_SERVICE_URL`, `MULTIMODAL_API_KEY`, `MULTIMODAL_SERVICE_TIMEOUT` | `flobrain/settings.py`, `brain/llm/multimodal_adapter.py` | see 2.1 |
| `MONGO_HOST`, `MONGO_PORT` | `memory/mongo_client.py` | `localhost`, `27017` |
| `S3_VAULT_BUCKET`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AES_MASTER_KEY` | `memory/tier_3.py` (at import) | `flobrain-cold-vault`, AWS default, empty, empty, **64 zeros** |
| `MEMORY_NODE_CUTOFF_DAYS`, `MEMORY_TOKEN_CUTOFF_DAYS`, `GC_CHUNK_SIZE` | `memory/reclassification.py` via `getattr(settings, ...)` (not env) | 90, 90, 500 |

Set but never read by Django: `REDIS_URL` (compose only), and `LLM_PROVIDER`, `LLM_DEFAULT_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `INTERNAL_API_KEY`, `NEXT_PUBLIC_API_URL` (named in the report).

Local `.env` defines (names only): `DEBUG`, `DB_ENGINE`, `SECRET_KEY`, `ALLOWED_HOSTS`, `MULTIMODAL_SERVICE_URL`, `MULTIMODAL_API_KEY`.

### 2.3 URL map (`flobrain/urls.py` + app `urls.py`)

All app URLconfs are included at the root with no prefix. Matches spec Section 2.4 exactly, with these details:

| Path | View | File |
|---|---|---|
| `/` | `home` (function view) | `users/views.py` |
| `/admin/` | Django admin | |
| `/api/auth/register/`, `signin/`, `signout/`, `refresh/` | `RegisterView`, `LoginView`, `LogoutView`, `RefreshView` | `users/views.py` |
| `/api/profile/`, `change-password/`, `delete/` | `ProfileView`, `ChangePasswordView`, `DeleteAccountView` | `users/views.py` |
| `/api/settings/preferences/`, `/api/settings/preferences/<uuid:pk>/` | **one** view `UserPreferencesListCreateView` for both | `users/views.py` |
| `/api/settings/presets/` | `PresetPreferencesListView` | `users/views.py` |
| `/api/brain/chats/`, `<int:chat_id>/`, `<int:chat_id>/send/` | `ChatListView`, `ChatDetailView`, `SendMessageView` | `brain/views.py` |
| `/api/memory/graph/`, `nodes/<str:pk>/`, `save/` | `MemoryGraphView`, `MemoryNodeDetailView`, `MemorySaveView` | `memory/views.py` |
| `/api/model-registry/`, `names/`, `<int:pk>/` | `AIModelListCreateView`, `AIModelNamesView`, `AIModelDetailView` | `model_registry/views.py` |
| `/api/dashboard/health/`, `memory-activity/`, `error-logs/` | `DashboardHealthView`, `DashboardMemoryActivityView`, `DashboardErrorLogView` | `dashboard/views.py` |
| `/api/contact/` | `ContactView` | `contact/views.py` |
| `/api/schema/`, `/api/swagger/`, `/api/redoc/` | drf-spectacular | |

Because one view serves both preference URLs, `GET`/`POST` also answer on `/api/settings/preferences/<uuid>/` and `PATCH`/`DELETE` also answer on the list URL (with `pk=None`, returning 404).

### 2.4 Authentication (`users/jwt_utils.py`, `users/views.py`)

Matches the spec and the report:
- PyJWT HS256 with `SECRET_KEY`. Access: `{sub, type: "access", exp: +1h, iat}`. Refresh: `{sub, type: "refresh", exp: +7d, iat}`. No `jti`.
- `get_user_from_request()` parses `Authorization: Bearer`, requires `type == access`, loads `users.User` by `sub`; any failure → `None` → the view returns 401.
- Signout needs no Bearer; blacklists `sha256(refresh)` only when its `sub` equals the posted `userId`. `refresh_tokens` is never written.
- Refresh returns `{access}` only, rejects blacklisted hashes and deleted users.
- `users/views.py` imports `rest_framework_simplejwt.authentication.JWTAuthentication` and `rest_framework.permissions.IsAuthenticated`; neither is used.
- Sign-in does not update `last_active`. Unknown email and wrong password give the same 401 (no enumeration).
- No rate limit on any auth endpoint.

### 2.5 Data model (tables)

`users` app (`users/models.py`, one migration `0001_initial`):

| Table | Model | Notes |
|---|---|---|
| `users` | `User` | UUID `id`, `username` (display name), `email` unique+indexed, `password_hash`, `provider`, `provider_id`, `created_at`, `last_active`; M2M `roles` through `user_roles`. No `is_authenticated` property |
| `roles`, `user_roles` | `Role`, `UserRole` | Unused by any endpoint |
| `sessions` | `Session` | Not the chat; unused |
| `refresh_tokens` | `RefreshToken` | Never written |
| `blacklisted_refresh_tokens` | `BlacklistedRefreshToken` | Used by signout/refresh |
| `guest_device_map` | `GuestDeviceMap` | Unused |
| `customer_billing`, `payment_history`, `group_billing`, `group_payment_history` | billing models | No endpoints |
| `preset_preferences`, `user_preferences`, `group_preferences` | preferences | `user_preferences` has API |
| `groups`, `user_groups` | `Group` (tree via `parent`), `UserGroup` | Unused |

Note: Django's own `auth_user`/`auth_group` tables also exist (admin login). Our `groups` table and Django's `auth_group` are different tables.

`brain` app (migrations `0001_initial`, `0002_message_token_fields`):
- `brain_chats`: **integer** PK (BigAutoField), `user` FK → `users.User` CASCADE, `title` default `New Chat`, `created_at`, `updated_at`; ordering `-updated_at`.
- `brain_messages`: integer PK, `chat` FK CASCADE, `role` (`user|assistant`), `text`, `image` (TextField, base64 or URL), `prompt_tokens`, `completion_tokens` (nullable, never written), `created_at`.

`memory` app (migration `0001_initial`):
- `memory_nodes`: `id` CharField(64) PK, `owner_id` CharField(64) default `system` (no FK to `users`), `name`, `binary_index`, `tier_level` 1/2/3, `metadata` JSON, `memory_type` (`chunk|summary|interaction|workflow`), `relevance`, `content_hash`, `size_bytes` (never written), `is_locked`, timestamps. Indexes (`tier_level`,`created_at`), (`owner_id`,`tier_level`).
- `memory_links`: `source`/`target` FK CASCADE, `relation`, `weight`.
- `token_dictionary`: `word` unique, `ref_count`, `last_accessed_at`, `frequency_score`.
- No `admin.py` (memory is not in the Django admin).

`model_registry` app (migration `0001_initial`): `ai_model_registry` as in spec 2.3, plus case-insensitive duplicate check in the serializer.

`dashboard` and `contact`: no models (`dashboard` has no `apps.py`).

### 2.6 Chat (`brain/`)

Send flow (`SendMessageView.post`): load chat (owner only, else 404) → validate → save user message (`text`, `image`) → retitle from the first 30 chars if title is `New Chat` → build messages (fixed system prompt `You are FloBrain, a helpful AI assistant.` + every message with text, in order; **images dropped**) → `get_llm_adapter().generate(messages, model)` → save assistant text → return `ChatDetailSerializer` with `usage {total_tokens, model, file_type}`.

Adapter (`brain/llm/multimodal_adapter.py`): flattens messages into one `System:/User:/Assistant:` string; sends `multipart/form-data` with the single field `text_input` to `POST {MULTIMODAL_SERVICE_URL}/process`; optional `Authorization: Bearer {MULTIMODAL_API_KEY}`; reads `result`, `model`, `file_type`, `total_tokens`. The `model` argument is accepted but **not sent**. `get_llm_adapter()` always returns this adapter (`brain/llm/__init__.py`); `LLMAdapter` is a `Protocol` in `brain/llm/base.py`.

Serializer shapes: message `{id: "msg-<pk>", role, type (= role), text, image, prompt_tokens, completion_tokens, timestamp}`; list `{id, title, timestamp, messages: []}`; detail `{id, title, timestamp, messages, usage}` where `usage` is `null` except on the send response. `ChatUsageSerializer` exists but is unused.

### 2.7 Memory (`memory/`)

HTTP surface is three endpoints (2.3). The graph, node detail and node PATCH all query `MemoryNode.objects` **without** an owner filter. `POST /api/memory/save/` takes `owner_id` from the body (default `system`).

Save pipeline (`MemorySaveView`, imports deferred inside the view): `sorter.distribute_to_tiers(body)` → `tier_3.migrate_to_cold_storage(node)` **always** → Chroma write if tier is still 1 or 2 → Tier 1 cache write if tier is 1. A successful S3 upload sets `tier_level = 3` (D7).

Module status:

| Module | Status | Wired to HTTP? |
|---|---|---|
| `sorter.py` | `HeuristicTierRouter` used; `MLTierRouter` (pickle at `/app/models/tier_router.pkl`, absent) unused; SHA-256 + MinHash dedup per owner | Yes (save) |
| `tier_1.py` | Django cache (LocMem) + in-process LRU of 5000 keys + pure-Python rANS; reads `metadata.tokens` | Yes (save) |
| `tier_2.py` | `chromadb.PersistentClient(path="/app/vector_db")` **created at import**; `hybrid_search` (vector + BM25 + link reweighting, filtered by `o_id`) | Save only; `hybrid_search` not called by any view |
| `tier_3.py` | boto3 client and AES-GCM cipher **created at import**; zstd level 19; retry 4x with backoff | Yes (save) |
| `context_assembler.py` | Token-budgeted assembler (tiktoken); passes the node object to `retrieve_from_cold_storage` instead of `vault_uri` (falls back to `metadata.raw_text`) | No |
| `compression.py` | Dictionary compression to uint16 using `token_dictionary` ids | No |
| `tasks.py` | Celery Hebbian task; needs `django_redis` connection `default` (no `CACHES`), no producer writes `cooccurrence_buffer` | No (no Celery app) |
| `reclassification.py` | Celery GC tasks + Prometheus metrics; **no `promote_to_active_context`** | No |
| `management/commands/warmup.py` | Imports the missing `promote_to_active_context` → crashes when run | CLI only |
| `mongo_client.py` | `MongoClient` at import (lazy connect), db `flobrain` | Yes (PATCH event log) |
| `workflow_service.py`, `knowledge_graph_service.py` | Mongo CRUD for workflows, steps, events, messages, llmcalls, knowledge edges | No |
| `embedding_service.py` | Loads `SentenceTransformer("all-MiniLM-L6-v2")` and imports `faiss` **at import**; neither package is in `requirements.txt` | No |
| `hybrid_retrieval_service.py` | Mongo + FAISS retrieval, filters by `user_id` after search | No |

### 2.8 Model registry, dashboard, contact

- Model registry: any authenticated user can create, edit and delete (D3). Only `AIModelNamesView` has `@extend_schema`. Not read by chat.
- Dashboard health: real DB check plus hardcoded `system_status: "online"` and `connected_devices: 3`. Memory activity counts **all** nodes in the system. Error logs: four hardcoded entries under the response key **`"error-logs"`** (hyphenated).
- Contact: `AnonRateThrottle` subclass at `5/hour`, LocMem cache so per process; since `NUM_PROXIES` is unset, DRF keys the throttle on the whole `X-Forwarded-For` header, which a client can change to bypass the limit. `csrf_protect` and `method_decorator` imported, unused. Validation errors `422 {"errors": {...}}`, SMTP failure `503`.

### 2.9 Admin

Registered: `Role`, `User` (default admin), `Chat`, `Message` (custom columns), `AIModel` (filter by provider type). Not registered: memory, preferences, billing, groups, sessions.

### 2.10 Tests

| File | Tests |
|---|---|
| `users/tests.py` | 4 (profile GET/PATCH, with and without token) |
| `memory/tests.py` | 4 (graph fields, node detail, PATCH; Mongo mocked). Nodes are created with the default owner `system`, so **these tests will need updating with the D2 fix** |
| `model_registry/tests.py` | 14 (CRUD, names, validation, duplicates, 401). `test_create_and_read_registered_model`, `test_update_registered_model`, `test_delete_registered_model` create/edit/delete as a normal user, so **they will need updating with the D3 fix** |
| `brain`, `dashboard`, `contact` | none |

**CI hazard:** `memory/test_crud.py`, `test_mongo.py`, `test_embeddings.py`, `test_hybrid_retrieval.py`, `test_knowledge_graph.py` are manual scripts that write to a live MongoDB or build a FAISS index **at import time**. Django's runner discovers `test*.py`, so `manage.py test` (no labels) or `manage.py test memory` imports them, which either crashes (no `faiss`) or writes to whatever Mongo `MONGO_HOST` points at. Today's safe command must name `memory.tests` explicitly.

### 2.11 OpenAPI

`/api/schema/` lists all 23 paths but only `GET /api/model-registry/names/` has a response schema (21 views fail with "unable to guess serializer"). The security schemes advertised are `basicAuth`, `cookieAuth` and `tokenAuth`; there is **no Bearer JWT scheme**, so Swagger "Authorize" cannot call the real API. Six operationId collisions come from views that serve both list and detail URLs.

### 2.12 Dependencies (`requirements.txt`)

Unpinned or loosely pinned (`>=`). Installed but unused by any import in the backend: `djangorestframework-simplejwt` (one unused import), `SQLAlchemy`, `networkx`, `opencv-python-headless`, `reportlab`. Imported but missing: `faiss`, `sentence-transformers` (only in `embedding_service.py`). No WSGI/ASGI server (`gunicorn`, `uvicorn`, `daphne`) and no `channels`.

---

## 3. Differences: spec and report vs code (code wins)

"Spec" = `FLOBRAIN_V2_CURSOR_PROMPT.md`; "Report" = `mohamed.md`.

### 3.1 Backend

| # | Source says | Code shows | Where | Impact on V2 |
|---|---|---|---|---|
| B1 | Report: send needs at least one of `text` or `image` | `SendMessageSerializer.text` is a required field (`allow_blank=True` but not `required=False`). An image-only request **without** a `text` key returns 400; `"text": ""` + image works | `brain/serializers.py` | Keep for V1; V2 thread send uses its own serializer |
| B2 | Report: service errors become an assistant message starting with `Error:` | True for HTTP errors and connection errors only. A non-JSON body (`json.JSONDecodeError`), a read timeout (`TimeoutError` after connect), or any other exception is **not caught**: the request returns 500 and the user message is already saved with no reply | `brain/llm/multimodal_adapter.py`, `brain/views.py` | V2 adapter path must catch everything and map errors (spec 8.1 item 8) |
| B3 | Report: memory detail/PATCH listed without comment | Node detail **and PATCH** are not owner-scoped either: any user can read and edit any node | `memory/views.py` | Folded into D2 (Decision E12) |
| B4 | Report: PATCH allowed fields `name`, `memory_type`, `relevance` | Values are not validated: any `memory_type` string is saved (bypassing choices), a non-numeric `relevance` raises an unhandled DB error (500) | `memory/views.py` | Fix with D2 (serializer) |
| B5 | Report: Mongo failure in PATCH returns 500 after save | Confirmed. Also `pymongo.MongoClient` is constructed at import of `memory/views.py`, so every process creates a client even if Mongo is never used | `memory/views.py`, `memory/mongo_client.py` | Q36 |
| B6 | Report: `UserPreferencesSerializer` returns preset details | The `preset_detail` field has no `source` and the model has no such attribute; DRF silently skips it, so **`preset_detail` never appears** in responses | `users/serializers.py` | V1 behaviour; TECH_DEBT |
| B7 | Report: preferences list/detail endpoints | One view serves both URLs, so detail methods answer on the list URL and vice versa; `DELETE` returns 204 **with a body** | `users/urls.py`, `users/views.py` | TECH_DEBT |
| B8 | Report: password min length 8 | True, but the four `AUTH_PASSWORD_VALIDATORS` in settings are never applied | `users/serializers.py` | V2 password set/reset must call `validate_password` |
| B9 | Report: memory tests in `memory/tests.py` | Five extra `memory/test_*.py` files are import-time scripts against live Mongo/FAISS (Section 2.10) | `memory/` | Decision E15 |
| B10 | Report: `binary_index` counter 1..65535 then wraps | After the wrap, the next index is computed from the max existing value (65535), so **every new node gets 1** forever | `memory/sorter.py` `_get_next_binary_index` | TECH_DEBT (not used by V2) |
| B11 | Report: save with S3 failing keeps original tier | True, but missing AWS credentials raise `NoCredentialsError` (a `BotoCoreError`), which the retry decorator retries 4 times with sleeps (roughly 3.5 to 10.5 s) on every save | `memory/tier_3.py` | TECH_DEBT; Phase 7 moves writes to a worker |
| B12 | Spec 2.4: schema "has no request/response schemas" | Confirmed, plus: no Bearer security scheme is declared; 6 operationId collisions | Section 2.11 | V2 adds `BearerJWTAuthentication` with an OpenAPI extension |
| B13 | Spec 2.2: Python 3.11 | Docker yes; the local (untracked) `.venv` is Python 3.14.3; `setup_venv.sh` prefers 3.12 | `Dockerfile`, `setup_venv.sh` | CI pins 3.11 |
| B14 | Report 4: `docker compose` is the run path | The production image `CMD` is `python manage.py runserver 0.0.0.0:8000` (Django's dev server) with **no** `migrate`; only compose runs `migrate` | `Dockerfile` | Q28, Q29, Decision E26 |
| B15 | Spec 2.4: model registry "in the repo but not in the deployed schema" | In the local SQLite DB the `model_registry 0001_initial` migration is also unapplied | `db.sqlite3` (untracked) | Q30 |
| B16 | Spec 12: health check on `/` | `/` returns `{"message": "Welcome to the users home page!"}` through `CommonMiddleware`, so it is subject to `ALLOWED_HOSTS`; there is no `/healthz` | `users/urls.py` | Decision E18 |
| B17 | Report: `dashboard/error-logs/` returns error logs | Response key is `"error-logs"` (hyphen), not `error_logs` | `dashboard/views.py` | Keep for V1 |
| B18 | Spec 2.2 / report: Redis not configured | Confirmed; also no `celery.py`, and `memory/tasks.py`/`reclassification.py` import `celery` and `prometheus_client` at module level | `memory/` | Decision E17 |
| B19 | Report: throttle per process | Also client-spoofable through `X-Forwarded-For` because `NUM_PROXIES` is unset | `contact/views.py`, settings | Decision E19 |
| B20 | Spec 2.3: `refresh_tokens` never written | Confirmed. Tokens have no `jti`, so per-session revocation needs a new claim | `users/jwt_utils.py` | Phase 0 V2 tokens add `jti` |

Everything else in the report's sections 1 to 20 matched the code (paths, request/response shapes, defaults, tier rules, Tier 3 format, assembler bug, missing `promote_to_active_context`, hardcoded dashboard values).

### 3.2 Frontend

| # | Spec says (2.6, 10.2) | Code shows | Where |
|---|---|---|---|
| F1 | Next.js 16, React 19, TS 5 | Confirmed: `next 16.2.6`, `react 19.2.1`, `typescript 5.9.3` (lockfile). `eslint-config-next` is `16.0.10` (version skew) | `flobrain-website/package.json`, lockfile |
| F2 | Turbopack | `next.config.ts` sets `turbopack.root`; scripts are plain `next dev`/`next build` | `next.config.ts` |
| F3 | Tailwind | **Tailwind v4** (`4.1.18`) via `@tailwindcss/postcss`; no `tailwind.config.*`, no `@theme` block | `postcss.config.mjs`, `src/app/globals.css` |
| F4 | shadcn/ui (Radix) | `components.json` exists (style `new-york`) but its `ui` alias points to `@/components/layout`; there is **no `components/ui/`**. Primitives: `button`, `card`, `dialog`, `input`, `label`. Radix packages: dialog, label, slot only | `components.json`, `src/components/layout/` |
| F5 | Route protection via `AuthContext` | No global guard and no `middleware.ts`. Only `/checkout` and `/payment` redirect to `/signin`. `/brain`, `/memory`, `/dashboard`, `/profile` render for anonymous users and fail at the API. `(app)/layout.tsx` writes `sessionStorage.isAuthenticated = "true"` on mount | `src/contexts/AuthContext.tsx`, `src/app/(app)/layout.tsx` |
| F6 | Tokens in `localStorage` | Confirmed: `flobrain_access_token`, `flobrain_refresh_token`, `flobrain_user_id`. `isAuthenticated = !!userId` | `src/contexts/AuthContext.tsx` |
| F7 | Axios refreshes on 401 | Confirmed; excluded paths `/api/auth/(signin|register|refresh)/`; on refresh failure clears tokens | `src/lib/axios.ts` |
| F8 | `NEXT_PUBLIC_API_URL` | Confirmed; `NEXT_PUBLIC_API_BASE_URL` appears nowhere. Fallback when unset is **`https://api.flobrain.ai`** (the README says `http://127.0.0.1:8000`), so a misconfigured local or preview build talks to production | `src/lib/axios.ts:16` |
| F9 | Brand tokens `--fb-*` with generic names (accent, primary...) and light tokens under `:root` | Tokens are **page-scoped** (`--fb-brain-*`, `--fb-dashboard-*`, `--fb-auth-*`, `--fb-page-bg`, `--fb-text`, `--fb-text-muted`, `--fb-card-*`). There is no `--fb-accent`/`--fb-primary`. Light values are under **`.light`**, dark under **`.dark`**; `:root` only holds `--radius: 0.5rem` and a few surface helpers. Dark values match the spec (`--fb-brain-accent #a855f7`, `--fb-brain-btn #9333ea`, `--fb-page-bg linear-gradient(90deg,#290036 0%,#070014 100%)`, `--fb-text #e2e8f0`, `--fb-text-muted #94a3b8`, success `#34d399`, error `#f87171`). Radius in `:root` is 0.5rem (8px), not 12px | `src/app/globals.css` |
| F10 | Font Inter | Loaded twice: a Google Fonts `@import` in `globals.css` and `next/font/google` in `layout.tsx` | `src/app/globals.css`, `src/app/layout.tsx` |
| F11 | React Query | Confirmed: `@tanstack/react-query 5.90.21`, client in `src/lib/query-client.ts` (`staleTime 60s`), provider in `src/components/providers/AuthProviderWrapper.tsx`. No Zustand/Redux | |
| F12 | Chat usage type | `ChatUsageApi` expects `prompt_tokens`, `completion_tokens`, `provider?`, `estimated?`, which the backend never sends; send body is `{text, image}` (no `model`) | `src/lib/api.ts` |
| F13 | Markdown sanitized (spec 10.3 wants it) | `react-markdown 10` + `remark-gfm`, **no** `rehype-sanitize`/DOMPurify. Raw HTML is not rendered (no `rehype-raw`) and react-markdown's default URL transform strips `javascript:` links, so the current risk is low. **No `dangerouslySetInnerHTML`** anywhere in `src/` | `src/app/(app)/brain/components/ChatArea/index.tsx` |
| F14 | i18n | **None**: no library, no catalogs, `<html lang="en">`, no `dir` | `src/app/layout.tsx` |
| F15 | Tests | Vitest 4 (jsdom) with **44** test files under `src/`; **no Playwright**. ESLint config ignores all `*.test.*` files | `vitest.config.ts`, `eslint.config.mjs` |
| F16 | Sentry, GA4 | Sentry 10.60 (client/server/edge configs, Replay). GTM id `GTM-KB2X98N3` hardcoded in `src/lib/analytics.ts`; GA4 via `@next/third-parties` only if `GA_MEASUREMENT_ID` is set. No web-vitals reporting | `src/lib/analytics.ts`, `src/instrumentation*.ts` |
| F17 | V1 pages `/brain`, `/memory`, `/dashboard`, `/home` | All exist. `/` is the marketing home (`src/app/home/index.tsx`, with `userLogged` hardcoded `false`); `/home` is the logged-in home. `/forgot-password` exists as a UI stub with no API | `src/app/` |
| F18 | Stripe used by V1 frontend (spec Phase 17) | Confirmed in `/checkout`, `/payment` (`@stripe/stripe-js`, `@stripe/react-stripe-js`); no backend Stripe code | |
| F19 | (not in spec) | Three 0-byte stray files at the frontend root: `flobrain-website@0.1.0`, `tsc`, `memory-graph`. Node version in `Node.nvmrc` (`20`), not `.nvmrc` | `flobrain-website/` |

### 3.3 Deployment and CI

| # | Spec says (2.2, 12) | Repo shows |
|---|---|---|
| P1 | CloudFormation stacks `flolabs-dev-networking`, `flolabs-dev-application`; confirm against templates | **No IaC in this repository** (no CloudFormation, CDK, Terraform, ECS task definition JSON, buildspec or deploy script for the API). The names and traps appear only in the spec. Q27 |
| P2 | Migrations on ECS: to discover | Not defined anywhere in the repo (Q28) |
| P3 | (CI implied by Decision 45) | `.github/workflows/backend-ci.yml` is named "Backend CI" but runs black/ruff/mypy/pytest on **`flobrain-cloud/`** only. **The Django backend has no CI.** `website-ci.yml` runs lint, typecheck, build for the website. `vercel-deploy.yml` deploys the website to Vercel (preview on PRs to `main`, production on push to `main`) |
| P4 | Backend deploy | Manual (no workflow; `docs/FIX_LOGIN_AND_CHAT.md` describes manual steps) |
| P5 | Frontend at www.flobrain.ai | Vercel, via the GitHub Action (`vercel.json` disables Vercel's own git deploys) |

---

## 4. Multimodal service contract

The multimodal service is **not in this repository** (no `/process` handler accepting `text_input` exists anywhere, including `legacy/`; `flobrain-cloud/` is a different service). The only facts available come from the Django client:

| Item | Known |
|---|---|
| Endpoint | `POST {MULTIMODAL_SERVICE_URL}/process` |
| Request | `multipart/form-data` with one field, `text_input` (the flattened conversation) |
| Auth | `Authorization: Bearer {MULTIMODAL_API_KEY}` if set (whether the service requires it is unknown) |
| Response fields read | `result`, `model`, `file_type`, `total_tokens` |
| Transport | default `http://` to a public IP |

Unknown, listed in `OPEN_QUESTIONS.md` Q1: `model`, image, document, audio, structured messages, credential reference, token breakdown, error codes, validation and embeddings endpoints.

---

## 5. Deployment as it exists

- Image: `flobrain-core/backend/Dockerfile` (`python:3.11-slim`, `pip install -r requirements.txt`, `postgresql-client`, `COPY . /app/`, `CMD runserver 0.0.0.0:8000`). No `HEALTHCHECK`, no non-root user, no `collectstatic`.
- `.dockerignore` excludes `.git`, `.env*`, venvs, `__pycache__`, logs, `db.sqlite3`, `vector_db/`, so secrets and local DBs do not enter the image. No `.env` or `db.sqlite3` is tracked in git.
- Local stack: `flobrain-core/backend/docker-compose.yml` (Postgres 15 on 5432, web on 8000 with `migrate` then `runserver`, `mongo:latest` unexposed with no init scripts, Redis 7 on 6379 unused by Django).
- Production (from the spec, unverifiable here): ECS Fargate behind an ALB, RDS Postgres, `ALLOWED_HOSTS="*"` because the ALB health check sends the task IP as `Host`.
- Chroma writes to `/app/vector_db` inside the container: on Fargate that is ephemeral and per task (Q35).

---

## 6. Known defects: status after verification

| # | Spec defect | Verified? | Notes |
|---|---|---|---|
| D1 | No role enforcement | Yes | `Role`/`UserRole` never read |
| D2 | Memory not owner-filtered | Yes, and wider | Also node detail and PATCH (B3) |
| D3 | Anyone can write the model registry | Yes | 3 existing tests assume it (2.10) |
| D4 | `CORS_ALLOW_ALL_ORIGINS = True` | Yes | |
| D5 | Zero `AES_MASTER_KEY` default | Yes | Cipher built at import in `tier_3.py` |
| D6 | Chat: no RAG, image not sent, `model` not forwarded, token fields unwritten | Yes | |
| D7 | Save freezes to S3 first | Yes | Plus B11 |
| D8 | Celery/Redis/GC/warmup broken; faiss/sentence-transformers missing | Yes | |
| D9 | Signout without live token; `refresh_tokens` empty | Yes | Plus no `jti` (B20) |
| D10 | Hardcoded dashboard values | Yes | |
| D11 | OpenAPI without serializers | Yes | Plus no Bearer scheme (B12) |
| D12 | Deployed API older than repo | Unverifiable here | Q30 |

New defects found during Discovery (for `TECH_DEBT.md` when Phase 0 creates it, unless a phase fixes them): B1, B2, B4, B6, B7, B8, B9, B10, B11, B14, B16, B19, F5, F8, F15 (ESLint skipping tests), P3.

---

## 7. What this means for V2 (short)

1. **There is no CI for the code V2 changes.** Phase 0 must add Django backend CI before or with the first V2 migration (Decision E27), and fix the test-discovery hazard (E15).
2. **Production runs the Django dev server and has no documented migration step.** Every V2 phase adds migrations, so Q28 and Q29 must be answered before the first V2 deploy.
3. **The V1 isolation fixes (D2, D3) change V1 behaviour on purpose** and break about 7 existing tests that encode the old behaviour (up to 4 in `memory/tests.py`, 3 in `model_registry/tests.py`); those tests are updated in the same PR, as the spec asks.
4. **The memory system needs storage and an embedder before Phase 7**: Chroma on ephemeral container disk (Q35) and nothing that produces embeddings (Q26).
5. **Frontend has no i18n, no route guard, no Playwright and no global design tokens**, so Phase 0's frontend scope (app shell, guard, i18n, theme tokens, e2e harness) is all new work rather than extension.
6. **The multimodal contract is the main external dependency** for Phases 5, 7 and 9 (Q1, Q13).

---

## 8. Addendum: changes on `main` after Discovery (2026-10-20)

Discovery audited `origin/main` at `7dbedb2`. Before Phase 0 started, `origin/main` moved to `ecb0a76`. Frontend commits (#252, microphone input, Font Awesome files) do not affect the audit. Commit `98a7756` (PR #250, "address code review comments on health, error-logs, memory, auth, docker") changes the backend:

| Area | Change in PR #250 | Effect on this audit |
|---|---|---|
| `memory/views.py` | Graph scoped to `owner_id = str(user.id)`; save forces `owner_id` from the token; save errors no longer echo the exception text | D2 partly fixed. Node detail and PATCH are **still unscoped** (B3), PATCH still unvalidated (B4) |
| `dashboard/views.py`, `dashboard/services.py` (new) | Memory activity scoped to the caller. Health now checks Postgres **and** MongoDB, derives `system_status`, and counts `connected_devices` from `refresh_tokens`/`guest_device_map` | D10 done. `connected_devices` is effectively always 0, because nothing writes `refresh_tokens` (D9) and nothing writes `guest_device_map`. The Mongo ping has no timeout (Q39) |
| `dashboard/views.py` | Error logs read from Mongo `workflow_steps` for the caller's workflows; **response key renamed `"error-logs"` → `"error_logs"`** | **V1 contract change.** The V1 frontend still reads `"error-logs"`, so the dashboard alerts are silently empty (Q38). This breaks spec rule 2 (V1 shapes stay) |
| `users/views.py` | Signout now requires a valid Bearer token and a `refresh_token` (or `refresh`) belonging to the caller; `userId` in the body is ignored | **V1 contract change.** D9's V1 half is now fixed. The V1 frontend keeps working because its Axios interceptor adds the Bearer header; a client that signs out after its access token expired gets 401 first, then the interceptor refreshes and retries |
| `docker-compose.yml` | Healthchecks for db, Mongo, Redis; Mongo gets a named volume | Local only |
| `memory/tests.py` | **Not updated** | `main` is red: `test_graph_maps_api_visualization_fields_to_model_fields` fails (nodes owned by `system`). Fixed in PR 0a by aligning the fixture |

Table 3.1 and section 6 above describe `7dbedb2`; read them together with this addendum.

---

## 9. Infrastructure ground truth (2026-10-20)

Read-only AWS audit on 2026-10-19/20. No account IDs are repeated here. No secret values. Nothing in AWS was changed.

### FloBrain backend

- ECS service `flolabs-dev-django-service` on cluster `flolabs-dev-cluster`, task definition `flolabs-dev-django:5`, Fargate, us-east-1. ALB terminates HTTPS (ACM cert for `api.flobrain.ai`). HTTP redirects to HTTPS.
- Image `flobrain-backend:latest` (mutable tag), last pushed 2026-08-19. The task definition sets no command and no entrypoint.
- Container health check: `GET http://localhost:8000/` (the V1 home view, not `/healthz`).
- ECS Exec is disabled. No scheduled tasks. One task-definition family.
- RDS `flolabs-dev-postgres`: PostgreSQL **15.17**, `db.t3.micro` (1 GB RAM), single-AZ, encrypted, not public, 7-day backups. Reachable only from the ECS security group. No SQL access from the console (no Data API, no bastion). Q11 stays open.
- S3 `flolabs-dev-uploads`: Block Public Access on, SSE-S3, versioning on. No `archive/` objects. No `flobrain-cold-vault` bucket.
- Not present: DocumentDB/Mongo, ElastiCache/Redis, SQS, EFS, Route 53 zones, a staging stack, EC2 instances in this account.
- NAT gateway public IP: `98.89.195.180`. Outbound calls from the ECS tasks leave from this address.

Env vars are plain text on the task definition (12 names). No Secrets Manager and no SSM.

| Set on the task | Not set |
|---|---|
| `AWS_REGION`, `DB_PORT`, `DB_PASS`, `DB_USER`, `DB_NAME`, `DB_HOST`, `MULTIMODAL_SERVICE_URL`, `CSRF_TRUSTED_ORIGINS`, `ALLOWED_HOSTS` (`*`), `SECRET_KEY`, `DEBUG` (`False`), `AWS_STORAGE_BUCKET_NAME` (`flolabs-dev-uploads`) | `S3_VAULT_BUCKET`, `MONGO_HOST`, `AES_MASTER_KEY`, `MULTIMODAL_API_KEY`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_BASE_URL`, `HR_WEBHOOK_SECRET`, `DRF_NUM_PROXIES`, `CREDENTIALS_ENCRYPTION_KEY` |

`AWS_REGION` and `AWS_STORAGE_BUCKET_NAME` are not read by this branch's Django settings.

### How production starts, and when migrations run

The task definition sets no command, so the image decides. `flobrain-core/backend/Dockerfile` has no `ENTRYPOINT`. Its `CMD` is `python manage.py runserver 0.0.0.0:8000`. There is no entrypoint script in `flobrain-core/`.

Migrations do **not** run when a container starts. The only `migrate` in the repo is `flobrain-core/backend/docker-compose.yml`, which is local. ECS Exec is disabled and there is no scheduled task, so this repo does not show a production path that applies migrations. Two web tasks cannot race a migrate-on-boot today, because boot does not migrate. They also cannot apply new V2 migrations until a human runs a one-off task (see `INFRA_CHANGES.md`). The Dockerfile is unchanged.

### Multimodal service (what V1 calls)

`MULTIMODAL_SERVICE_URL` is `http://35.153.90.219:8000/` (already the repo default). That address is an EC2 `t3.small` with no GPU, named `multi-modal-perception`, in a **separate** AWS account, us-east-1, on an Elastic IP.

It is plain HTTP. Port 8000 is open to the internet. No auth, no load balancer, no TLS, no logs. It is a thin FastAPI proxy to OpenAI `gpt-4o-mini` (`MAX_TOKENS=256`). On error it returns HTTP 200 and a normal-looking body: `Perception system temporarily unavailable. Echoing input...`.

The main account's us-east-2 has an unfinished plan to move it to ECS Fargate (empty clusters, an empty log group, no task definitions). Nothing runs there. There is no second running copy.

V2 must treat that body as a provider error. It must not store it as an assistant reply or as memory, and it must not send org documents, memory, or files through this adapter. See the provider default in `OPEN_QUESTIONS.md` and Phase 7 in `PLAN.md`.
