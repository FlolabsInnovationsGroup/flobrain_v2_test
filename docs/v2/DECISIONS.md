# FloBrain V2: Decisions

Status: updated 2026-10-20. Spec decisions 1–50 are the working defaults. Engineering decisions record what this branch already does and what is chosen but not built. Phase 7 (E29–E32) is not started.

Two parts:

1. **Spec decisions**: every `[DECISION]` from `docs/v2/FLOBRAIN_V2_CURSOR_PROMPT.md` (Section 4, numbered 1 to 50, plus the inline decision in Section 7). They are the defaults; the FloBrain team can override any of them by editing the row and adding a dated note.
2. **Engineering decisions** (`E1`, `E2`, ...): choices made during Discovery where the spec left room, or where the code forced a choice. Each one says why and how to reverse it.

When a decision is overridden, keep the old text struck through and add `Overridden YYYY-MM-DD by <name>: ...` so the history stays readable.

---

## Part 1: Spec decisions (copied from the master prompt, Section 4)

| # | Topic | Decision |
|---|---|---|
| 1 | Roles | Two layers. **Org role** per user per organization: `owner` (= "System Owner"), `admin`, `member`. **Team role** per team membership: `lead` or `member`. "Team Lead / PM" = anyone with `lead` on at least one team or `lead` on a project. "Intern" is a member with an internship profile. Keep `users.user_type` (`company_member`, `company_lead`, `company_adm`, `personal`) as a **derived, denormalized** field for sign-in gating and display; memberships are the source of truth. |
| 2 | Who can create/assign tasks | Any room member can create a task in that room's board. A member can assign a task only to **themselves**. Assigning to others, reassigning, and setting due dates on others' tasks: team lead of that team, org admin, owner. Members can move/update tasks assigned to them or created by them. |
| 3 | Task statuses | `to_do`, `in_progress`, `done` (UI: To Do / In Progress / Done). "Blocked" is a flag (`is_blocked`, `blocked_reason`, `blocked_since`), not a column. |
| 4 | Task filters | All, My Tasks (assigned to me), Assigned by me, Assigned to [person], Completed. |
| 5 | Task assignment form | Task name*, Assignee(s)*, Due date*, Priority (High/Medium/Low, default Medium), Team(s) (multi-select, active teams), Project (optional, active projects), Description (optional). |
| 6 | Member status | Two fields. `presence`: `online`, `away`, `on_leave`, `offline` (online/away derived from activity; `on_leave` set manually). `employment_status`: `active`, `paused`, `graduated`, `terminated`, `offboarding`. "Active" = `employment_status == active`; anything else = "Inactive". Directory filters: All, Online, Away, Leave, Active, Inactive. |
| 7 | Inactive members | Read access to their past work stays. An inactive member **cannot sign in**. Nobody can send new 1:1 messages to them or assign new tasks to them. Their rooms show them greyed out. |
| 8 | Who changes member status / registers members | Team lead for members of their own team; org admin/owner for anyone. Promoting someone to `lead` or `admin`: admin/owner only. |
| 9 | Sign-in | Email + password, or the org's SSO when configured (Phase 17). No self-registration in V2 (`/api/v2/auth/*` has no register). Only users with an active org membership (`user_type` in `company_*`) can sign in to the V2 workspace. V1 `/api/auth/register/` stays for V1 personal users but its accounts cannot open the V2 workspace. |
| 10 | First login | User created by a lead/admin gets an emailed temporary password and `must_change_password = true`. After sign-in they must set a new password and add a phone number. Then the Cockpit. |
| 11 | Rooms | Auto-created room for every team and every project (members synced from team/project membership). Direct rooms for 1:1. Group rooms for 2+ people on demand. Tabs: Chat, AI Chat, Tasks, Docs, Calendar, Recordings, Report, Team. |
| 12 | Room AI chat privacy | AI chat threads are **per user per room** (private to the asker). The AI can read room messages, tasks and docs **that the asking user can see**. Nothing a user cannot access may enter the prompt. |
| 13 | Timestamps | < 1 min: "just now". < 60 min: "X min ago". Same 24 h: "X hours ago". Older: device locale date/time via `Intl.DateTimeFormat`. Same rule in room chat and AI chat. |
| 14 | Tasks source of truth | Native FloBrain tasks. Notion task import/sync is an optional connector in Phase 15 (one-way import first; FloBrain stays the source of truth). |
| 15 | Time tracking (Flo Chronos) | Native in FloBrain: FloBrain users, `time_entries`, `tags`, projects, server-side live timer, `weekly_target_hours` per membership. Export to the legacy Chronos app is an optional adapter, off by default. |
| 16 | Hour categories | Each time entry has `category`: `onboarding`, `masterclass`, `projects` (default `projects`). The dashboard groups by it. |
| 17 | Impact score, weekly targets, capacity | `weekly_target_hours` on team membership (nullable, set by lead/admin). "Tasks done vs weekly target" uses `weekly_task_target` (nullable). **Impact score is undefined**: pluggable metric slot that shows "Not configured" until a formula is approved. Capacity = target hours minus logged hours this week (only if target set). |
| 18 | Commission & Leads | Feature-flagged per user (off by default, toggled by admin/owner). Members submit leads; admin/owner records commission amounts and status. Lead stages: Contacted, Meeting 1, In Progress, Won, Lost. Phase 12. |
| 19 | External tools vs plugins | Two features. *External tools* = links in the tool rail (defaults: Figma, Canva, Cursor, Notion, Discord, GitHub; users add custom name + URL). *Plugins* = encrypted credentials that let FloBrain AI read data from a tool (first: Notion). Opening Notion in a tab gives the AI no access. |
| 20 | LLM keys (BYOK) | Stored by the Django backend, encrypted, never returned. States: `pending`, `active`, `rejected`, `indeterminate`, `disabled`, `expired`. Model choices in chat = platform models (model registry) + providers where the user has an active key. **No silent fallback** from a user key to the platform key or to another provider. |
| 21 | Cockpit views | V2 ships Default, Focus, Custom (Phase 10). Clarity/Buddy/Command/Nebula modes are later vision; do not build them. |
| 22 | FloVault | Out of V2. V2 has per-room Docs & Knowledge Base. |
| 23 | Health Buddy / personal users | Out of V2. Personal users never see internship/company features. |
| 24 | Realtime | Django Channels with a Redis channel layer for chat, presence, notifications and timer sync. Requires ElastiCache: propose in `INFRA_CHANGES.md`. Until approved, polling fallback (React Query refetch every 5 s on open rooms) behind the same frontend hooks. |
| 25 | Voice/video | Phase 5 uses an external provider (Zoom SDK, LiveKit or Daily, decided in `OPEN_QUESTIONS.md`). Recordings are metadata + a playable URL (S3 presigned or provider URL). |
| 26 | Token storage on the frontend | Keep Bearer + existing refresh flow for compatibility. TECH_DEBT: move refresh token to an httpOnly cookie. Never render untrusted HTML (chat/markdown must be sanitized) because tokens are in `localStorage`. |
| 27 | Existing `roles`, `user_roles`, `groups` tables | Left unused. New `OrgMembership.org_role` and `Team`/`TeamMembership` replace them (roles must be scoped per org and per team). Do not delete the old tables in V2. |
| 28 | Room calendar for members | Every room has a calendar for its members (spec req. 10), overriding the Notion matrix row "Team calendar view: – for members". |
| 29 | Access requests | Members are restricted by default. They request a permission through `PermissionRequest`; a lead/admin who holds that permission approves, which creates a `PermissionGrant`. |
| 30 | BYOK gating | Member LLM keys are behind the `byok` feature flag (off by default). |
| 31 | Announcement notifications | `announcement` is an extra notification type beyond the 7 in the spec, with the default sound. |
| 32 | Memory is the AI's source of context | Phase 7 wires the existing (unused) memory code into the AI request path: rooms, docs, tasks, meeting transcripts and approved plugin data are indexed per organization with permission metadata; retrieval filters by what the asking user can read; answers that use memory show citations. Provider-side memory is never the source of truth. |
| 33 | AI actions | Buddies and room AI may **propose** actions. FloBrain validates arguments and permissions, shows an approval card, executes only after approval, and audits. Read-only actions on the user's own data need no approval. Every executable action is a registered tool with a JSON schema. |
| 34 | Buddy Builder | Any member can create a private buddy; sharing with a team requires team lead approval; org-wide requires admin. A custom buddy can only use sources and tools its creator can access; action tools always require approval. |
| 35 | Content Studio Buddy | Built-in buddy with its own workspace (Phase 9), reusing the in-house AI video editor pipeline (Claude Sonnet as editing brain). Rendering on the team's **JarvisLabs GPU** workers, not on API containers. |
| 36 | Social publishing | Direct publishing supported via **pluggable publishing connectors** connected by org admins (or a member with a grant). First: YouTube, LinkedIn, TikTok, Instagram, Facebook, X. Every publish requires explicit human approval and is audited; scheduled posts can be cancelled until they go out. |
| 37 | Consent for media | A person's face or voice can only be published with a recorded consent for that use. Meeting recordings are clipped only from meetings whose participants were notified that recording was on. |
| 38 | Languages | English and Arabic (RTL) first, then Turkish, French, Portuguese. Live chat translation translates on display per reader, keeps the original, labels translated messages. |
| 39 | Mobile and desktop | Mobile = installable PWA. Desktop = thin shell (Tauri preferred) only after the PWA is stable. No separate native codebases in V2. |
| 40 | Certificates and portfolio | Issued by an admin when an internship ends, from real data, signed, verifiable at a public URL with QR. Public portfolio is **opt-in per item**. |
| 41 | HR intake | The n8n HR automation pushes accepted applicants through an authenticated webhook that creates a pending member (no account active until a lead or admin confirms the team). |
| 42 | Public API and MCP | External access uses scoped personal access tokens (OAuth later), never session tokens. MCP server exposes read tools by default; write tools follow Decision #33. |
| 43 | Pulse | Built inside V2 (Phase 13) on `UsageEvent` and `AITrace`. Shown data is always real telemetry; synthetic data only in a labelled demo workspace. Public status page hosted separately (Phase 14). |
| 44 | Tracking ethics | Only records what the user starts (timer) or what happens inside FloBrain. No screen capture, keystroke logging or background device tracking. Personal analytics and org visibility are separate settings (Phase 16). |
| 45 | Release discipline | Staging plus CI/CD is part of Phase 0. Production only receives builds that passed staging. |
| 46 | Scheduled agents | Run with the creator's permissions **as evaluated at run time**; if the creator loses access or is deactivated, the agent pauses. Write actions from scheduled runs create approval requests; never unattended. |
| 47 | AI assignment | AI may suggest an assignee (workload, skills, history), never assigns on its own; suggestions explain their reason. |
| 48 | External agents (MCP client) | External agent/MCP output is untrusted data: shown and cited, never followed as instructions; implied actions go through approval. Owner maintains the allowlist; admins connect only listed servers. Imported tools are `ToolDefinition` (`risk=external`, `requires_approval=true`, `perm_key=external_agents.<server>.<tool>`); tool-list changes need owner re-approval. Context obeys R6 and `pii_redaction`; blocked entirely when `inference_scope=private_only`. |
| 49 | Pricing principle | No opaque credits. Admins see cost per task, per model and per team; BYOK has zero markup; budgets are enforced (Phase 7). |
| 50 | Sovereign mode | `OrgPolicy.inference_scope = external_allowed \| private_only`, overriding `RoutingPolicy`. In `private_only`: no external model API calls, external BYOK credentials set to `disabled`, external agents blocked, Content Studio/translation/transcription use self-hosted registry models or show as unavailable. |

### Inline spec decision (Section 7)

| # | Topic | Decision |
|---|---|---|
| 51 | Org context in V2 URLs | **Path-based**: `/api/v2/orgs/{org_id}/...` (not an `X-Org-Id` header). |

---

## Part 2: Engineering decisions from Discovery

Each item: decision, reason, how to reverse.

### Repository and process

**E1. Docs live in `FloBrain/docs/v2/`.** The master prompt is kept at its current name `FLOBRAIN_V2_CURSOR_PROMPT.md` (the prompt text calls it `CURSOR_PROMPT.md`; both mean the same file). Reverse: rename the file; nothing references the name in code.

**E2. Phase branches start from `main` and PRs target `main`.** `CONTRIBUTING.md` and `RELEASING.md` say feature work targets `development`, but `origin/development` was last updated 2026-01-11 and is 390 commits behind `origin/main`; recent PRs (#243 to #246) merged into `main`. The working copy is currently on `moodchanger_health_buddy_in_tembletes` (2 commits ahead of `main`, frontend templates). Phase 0 branches off an up-to-date `main` as `v2/phase-0-foundation`; later phases follow `v2/phase-<n>-<slug>`. Reverse: if the team revives `development`, retarget the PRs.

**E3. The backend source of truth is `FloBrain/flobrain-core/backend`.** `flobrain-core/api`, `flobrain-core/core`, `flobrain-core/workflow-db`, `flobrain-core/manage.py` and `flobrain-cloud/` are not extended in V2 (see AUDIT.md section 1.2 for what they are). Copies under the sibling `test/` and `clear/` folders outside the repo are ignored.

### Backend architecture

**E4. V2 is isolated from V1 by construction, not by convention.**
- V2 views inherit from one base class (`core_v2.views.V2APIView`, final name chosen in Phase 0) that sets `authentication_classes = [BearerJWTAuthentication]`, a V2 exception handler, V2 pagination and a default-deny permission.
- Global `REST_FRAMEWORK` defaults are **not** changed, because V1 views rely on them (V1 error shapes, V1 auth via `get_user_from_request`, V1 throttling).
- Reason: the spec requires every V1 path, request and response shape to stay identical. Reverse: none needed; V1 can migrate view by view later.

**E5. `users.User` gets `is_authenticated = True` and `is_anonymous = False` properties in Phase 0.** Safe for V1: no V1 view reads `request.user` for our custom `User` (V1 resolves users manually), and the DRF default authentication classes never return a `users.User`, so `AnonRateThrottle` on `/api/contact/` keeps its behaviour.

**E6. Permission engine lives in a new `organizations` app**: `organizations/permissions/` holds a code-defined registry of permission keys (one module listing every key, its matrix row and default per role), the `can(user, perm_key, obj=None)` function, and DRF permission classes built on it. Keys are strings (`tasks.assign_others`), not DB rows, so tests can enumerate them. Grants (`PermissionGrant`) reference keys by string and are validated against the registry.

**E7. UUID primary keys for all new tables.** Exception: `brain_chats` keeps its integer PK; V2 threads that reuse it expose the int id under `/api/v2/` only.

**E8. `ProjectMembership` is an explicit table** (the spec asked to decide). Columns: `project`, `user`, `source` (`team` = synced from the project's teams, `direct` = added by hand). Reason: project rooms, project leads and calendars need people who are on a project without being on all its teams, and an explicit table makes `can()` checks a single indexed lookup. Reverse: drop `direct` rows and derive from teams.

**E9. `user_type` derivation rule** (service `organizations.services.sync_user_type(user)`, run on every membership change):
`owner` or `admin` in any active org → `company_adm`; else `lead` on any team or project → `company_lead`; else an `active` org membership → `company_member`; else `personal`.

**E10. V2 errors and pagination are V2-only.** V2 exception handler returns `{"error": "<code>", "details": ...}`; codes are a fixed enum in code. V2 pagination: `page`/`page_size` (default 20, max 100); chat messages use an opaque `before` cursor (base64 of `created_at` + `id`).

**E11. V2 tunables live in one settings dict** `FLOBRAIN_V2 = {...}` (limits, page sizes, rate limits, lifetimes from spec Section 5.3), each overridable by environment variable. Org-level overrides go in `Organization.settings`.

**E12. Memory isolation (D2) also covers node detail and node PATCH.** The spec names `/api/memory/graph/` and `/api/dashboard/memory-activity/`; the code shows `GET/PATCH /api/memory/nodes/<id>/` leaks the same way (any user can read and edit any node). Outside scope returns `404`. Nodes owned by `system` stay in the database, visible only to `is_platform_admin`. No data is deleted.
- Update 2026-10-20: PR #250 (merged to `main` after Discovery, `98a7756`) already scoped the graph, memory activity and save (`owner_id` forced from the token). PR 0b only adds the missing pieces: node detail and PATCH scoping, PATCH validation, and the `is_platform_admin` view of `system` nodes.
- Update 2026-10-20 (Q11, decided): keep those nodes forever unless a human later asks to delete them. No migration and no reassignment. The row count is not required for rollout.

**E13. Model registry (D3): reads stay open to any authenticated user; writes need `is_platform_admin`.** `GET /api/model-registry/` and `/names/` keep their current behaviour so the V1 frontend and future model pickers keep working.

**E14. D10 (dashboard mocks): ~~add `"mock": true` fields, keep the old keys.~~** Superseded 2026-10-20: PR #250 replaced the hardcoded values with live checks (`dashboard/services.py`), so there is nothing left to label as mock. PR #250 also renamed the error-logs response key from `"error-logs"` to `"error_logs"` while the V1 frontend still reads `"error-logs"` (see AUDIT.md section 8, Open Question 38).

**E15. Make `manage.py test` safe for CI in Phase 0.** `memory/test_crud.py`, `test_mongo.py`, `test_embeddings.py`, `test_hybrid_retrieval.py` and `test_knowledge_graph.py` are manual scripts that run against live MongoDB/FAISS at import time; Django's test discovery imports them. Phase 0 moves them to `memory/manual_checks/` (renamed without the `test_` prefix) with no behaviour change. Reverse: move back.

**E16. One embedding and retrieval route: Postgres, with the vector store behind an interface.** The Mongo + FAISS path (`embedding_service.py`, `hybrid_retrieval_service.py`) is not put in the request path, so `faiss-cpu` and `sentence-transformers` are **not** added to `requirements.txt` (spec Section 8.5 asks for this choice). Update 2026-10-20: shared and production retrieval is pgvector (E16a). Chroma is local dev only, behind that same interface. The embedding model is E31 (Q26), not an open question. Reverse: wire `embedding_service` instead and add both packages.

**E16a. pgvector on the existing RDS for V2 knowledge retrieval.** Closed 2026-10-20 (Q35). RDS is PostgreSQL 15.17, so `CREATE EXTENSION IF NOT EXISTS vector` is available. Production and any shared environment use pgvector, not Chroma. The store sits behind an interface so Chroma remains possible for **local dev only**. Phase 7 adds a separate flag-gated migration. If the extension is missing, memory search shows "Not configured". The instance is `db.t3.micro` (1 GB); HNSW parameters stay conservative (`TECH_DEBT.md`). Nothing in Phases 0 to 6 depends on it.

**E17. Background jobs use a PostgreSQL-backed queue only.** Closed 2026-10-20 (Q17). Dev and tests may still run synchronously when `JOBS_EAGER=True`. In non-DEBUG, job-dependent features report "unavailable" instead of running inline. Redis and SQS are not in the account and are not the queue. Redis/Channels stays an unapproved proposal in `INFRA_CHANGES.md` for realtime. Celery is not the chosen broker (`celery` and `redis` remain unused packages in `requirements.txt`).

**E18. Health check: implement `/healthz` in code in Phase 0; pointing the ALB and container checks at it is an infra change.** A middleware placed before `CommonMiddleware` answers `GET /healthz` with 200 and no host validation. `GET /` keeps returning the current JSON. Tightening `ALLOWED_HOSTS` waits until the target group uses `/healthz` (spec Section 12).

**E19. Trusted proxy count via env, default unset.** `NUM_PROXIES` is read from `DRF_NUM_PROXIES`; V2 throttles and `AuditEvent.ip` use it. It is set to `1` in staging/prod through infra config, not hardcoded, because local and Docker runs have no proxy. Note: this also changes how the V1 contact-form throttle identifies clients (today it keys on the whole `X-Forwarded-For` header, which clients can spoof); that is a fix, recorded in the CHANGELOG.

**E20. Credentials encryption is a separate module from Tier 3.** `CREDENTIALS_ENCRYPTION_KEY` (spec 6.9) with AES-256-GCM, AAD = credential id + org id, `key_version` for rotation. It does not reuse `memory/tier_3.SecureCipher`, whose module builds its cipher at import time and silently defaults to an all-zero key.

**E21. A real `AES_MASTER_KEY` at the first V2 deploy.** Decided 2026-10-20 (Q12). `put_object` must succeed before `tier_level` becomes 3, and there is no vault bucket and no `archive/` object, so a failed S3 write leaves no ciphertext that needs the zero key. Production gets a new random 64-hex key at the first V2 deploy. `ALLOW_INSECURE_AES_MASTER_KEY` is an emergency switch only. This branch does not set the key. The startup check still refuses a missing or all-zero key when `DEBUG` is false.

### Frontend

**E22. V2 app lives in the existing Next.js app under the `/w/` URL prefix** with its own layout, auth guard and providers. V1 routes are untouched. The workspace is `src/app/w/[orgSlug]/...`. All V2 auth screens are also under `/w/` (`/w/signin`, `/w/first-login`, `/w/reset-password`), because route groups such as `(workspace)` do not change the URL and a `(workspace)/signin` page would collide with the V1 `/signin` page (amended 2026-10-20 at Phase 0 approval). The URL uses the org **slug**; API calls use the org **id** from `GET /api/v2/me` (Decision 51 is about the API).

**E22a. No production fallback for the API URL (fixes AUDIT F8, Phase 0 PR 0e).** In development the base URL defaults to `http://127.0.0.1:8000`; a production build fails if `NEXT_PUBLIC_API_URL` is unset. Applies to V1 and V2, since both use the same Axios instance (approved 2026-10-20).

**E23. Typed API client: `openapi-typescript` types + the existing Axios instance.** Types are generated from `/api/schema/` into `src/lib/v2/schema.d.ts`; a small typed wrapper sits on the existing Axios instance so the refresh-on-401 interceptor is reused, not duplicated.

**E24. i18n library: `next-intl`** (no i18n library exists today; see AUDIT.md). Catalogs in `messages/{en,ar}.json`; V2 strings only. V1 pages are not translated in V2.

**E25. V2 never renders user content as HTML.** Markdown in V2 goes through `react-markdown` with `rehype-sanitize` and no raw HTML. Discovery found no `dangerouslySetInnerHTML` in `flobrain-website/src`; a lint rule (`react/no-danger`) is added in Phase 0 to keep it that way.

### Telemetry

**E28. Telemetry from V1 paths is best-effort.** `UsageEvent`/`AITrace` writes from the V1 chat send path (PR 0d) are wrapped so any failure is logged and never changes the V1 response body or status code; a test proves V1 send still returns 200 when the telemetry write raises (approved 2026-10-20).

### AI and media

**E29. New V2 AI features use `direct`.** `AI_PROVIDER_BACKEND` selects a `ModelProvider`. `multimodal_legacy` wraps the V1 multimodal call and stays the production default for that V1 path. The HTTP 200 body `Perception system temporarily unavailable. Echoing input...` is a provider error: never an assistant reply, never memory. For V2, `direct` is the default path. `multimodal_legacy` is allowed in V2 only for room threads (Phase 7d), and only for the asking user's own text, with no room messages, tasks, docs, or memory added to the prompt. Translation, retrieval, embeddings, and credential checks do not use it. If `direct` is not configured, those features stay unavailable and do not fall back to legacy. V1 code paths stay unchanged. Local dev may set `direct` from an uncommitted `.env`. Production does not select `direct` until the platform key is in Secrets Manager. Extended 2026-10-20 with the Phase 7 amendments.

**E30. Voice and video is LiveKit, behind a provider interface.** Closed 2026-10-20 (Q2). Phase 5 calls LiveKit only through that interface. The `voice_video` flag stays default off, and no join URL is stored while it is off. Self-hosted LiveKit versus LiveKit Cloud is an infra choice (`INFRA_CHANGES.md`). Recordings come from whichever LiveKit deployment that choice picks. Not implemented in this step.

**E31. Embeddings go through an `Embedder` interface.** Closed 2026-10-20 (Q26). First model is **BGE-M3**. Fallback is **multilingual-e5**. Memory code calls the interface, not a model name. Every stored vector records the model name and the dimension. Memory search stays behind its flag until a human approves hosting. The main account has no GPU; where the model runs is `INFRA_CHANGES.md`. Not implemented in this step.

**E32. Transcription uses `ModelProvider`, then a small WER set.** Closed 2026-10-20 (Q14). Meeting transcription calls the same provider interface as E29, so the ASR can change without a meeting-code change. The repo will hold a small word-error-rate set in Arabic and English so later providers can be compared. That set is not added in this docs pass.

**E33. Future migrations use the one-off ECS task.** Decided 2026-10-20 (Q28). The procedure in `INFRA_CHANGES.md` is how V2 migrations run. How past migrations were applied is history and does not block the plan. The Dockerfile is unchanged.

**E34. Production `SECRET_KEY` length is enough.** Decided 2026-10-20 (Q31). The production key is 66 characters. The value is not written here. Rotation is still the separate `JWT_SIGNING_KEY` proposal.

**E35. Working defaults that are not final.** 2026-10-20. Q37, Q25, Q15, Q18, Q16, Q23, Q24, Q5, Q6, Q19, Q20, Q21, and Q22 may be built from the defaults in `OPEN_QUESTIONS.md` only while each value stays configurable. None of those defaults is hard-coded. Each stays open until the named owner confirms it. Q3 is decided: impact score stays "Not configured" until leadership approves a formula, and it stays separate from commissions.

**E36. A flag that is off returns 501.** New Phase 7 endpoints use `501` and `{"error": "not_implemented", "details": "..."}` when their feature flag is off. `503` is for a dependency that is down while the feature is on. The realtime ticket already shipped as 503 while its flag is off; that path stays until a later change. Decided 2026-10-20 with the Phase 7 plan.

**E37. Room access follows live membership; DMs and group rooms are private.** 2026-10-20 (found while preparing 7i). Leaving a team or a project removes the user from that team's room and from project rooms that no longer include them (`post_delete` signals plus pruning in `ensure_*`). Owners and admins can open team, project and org rooms without being members, so they can moderate. They cannot read `direct` or `group` rooms they are not in. Every list, search and retrieval path uses `rooms.services.accessible_rooms`. Q40 asks product/legal to confirm the DM rule.

**E38. BYOK keys go only to allowlisted HTTPS hosts, and org keys are for managers.** 2026-10-20 (7k). A customer key is sent only to a host in `BYOK_ALLOWED_HOSTS` over HTTPS, with redirects off, so a key cannot be used to reach an internal address or be forwarded. Org keys are visible and usable by `credential.manage` holders (owner, admin), as in `PHASE_7_PLAN.md`. Whether members may use an org key is Q41. Knowledge ask and translation still use the platform `direct` key only.

**E39. The person a proposal was made for approves it, and reports are built from rows.** 2026-10-20 (8c/8d). Decision 33 says FloBrain shows the approval card to the user; nobody else can decide another person's proposal (404). An approval re-checks the target for the approver at that moment, and a lost permission leaves the proposal open rather than failing it. Team reports are deterministic drafts that cite task and time-entry ids; a model rewrite can be added later behind the same citations.

### Deployment

**E26. Container command changes are infra changes.** The Dockerfile runs Django's development server (`runserver`). Decided in principle 2026-10-20 (Q29): switch to gunicorn with the first V2 deploy, through staging, in the ECS task definition. Not applied from this branch. ASGI/uvicorn waits until Channels lands.

**E27. CI first, CD later.** Today `.github/workflows/backend-ci.yml` (named "Backend CI") runs black/ruff/mypy/pytest on `flobrain-cloud/`, not on the Django backend, so the Django backend has no CI. Phase 0 adds a separate `django-backend-ci.yml` and leaves the existing workflows alone. It adds GitHub Actions jobs for backend (`check`, `makemigrations --check --dry-run`, tests on Postgres, schema generation with warnings-as-errors for `/api/v2/` only) and frontend (`tsc --noEmit`, lint, Vitest). Deploy-to-staging and promote-to-prod workflows are written as files but stay disabled until the staging stack in `INFRA_CHANGES.md` exists.
