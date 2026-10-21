# FloBrain V2 technical debt

Seeded from `AUDIT.md` §6 and Discovery extras. Update when a phase closes an item.

## Closed in Phase 0

| ID | What changed |
|---|---|
| P3 (Django CI) | `django-backend-ci.yml` (0a) |
| E15 | Manual Mongo/FAISS scripts moved out of test discovery (0a) |
| D2 remainder / B3 | Memory node GET/PATCH scoped (0b) |
| D3 | Registry writes need `is_platform_admin` (0b) |
| D4 | CORS allowlist (0b) |
| D5 (check only) | Startup AES check. Q12 decided: a new 64-hex key at the first V2 deploy; the insecure override is an emergency switch |
| Q38 | Error-logs returns both keys (0b) |
| E5 / B20 (jti on new tokens) | `is_authenticated` properties; `jti` on new JWTs (0c). Old tokens without `jti` stay valid |
| F8 | No production API URL fallback (0e) |
| F15 partial | V2 test files are no longer ESLint-ignored (0e). V1 `*.test.*` still ignored |

## Closed in the Stage B review

| Item | What changed |
|---|---|
| Room/file/announcement/recording isolation | 404 outside scope, 403 when the module or org is denied, with a denial test for each |
| Stub translation, transcript, summary, join URL | 501 or omitted. No placeholder text in the UI |
| Project rooms | `ensure_project_room` on project and membership saves |
| Chat paging | `useRoomMessages` plus cursor `next` |
| Browser proof | Playwright smokes for sign-in, switch, rooms, tasks, timer, denial |
| Icon font | `fa-solid-600.eot` restored; no other asset deleted versus `origin/main` |

Still deferred on purpose (see `PLAN.md`): LLM translation, Channels, S3, real meetings media, transcription workers, rich text, avatars, Report/Team/Recordings room tabs, highlight clips.

## From the 2026-10-20 infra audit (not implemented)

- **`JWT_SIGNING_KEY` (proposal only).** `users/jwt_utils.py` signs access and refresh tokens with HS256 and `settings.SECRET_KEY`. Password-reset tokens are random and stored as a hash; they do not use `SECRET_KEY`. Add a `JWT_SIGNING_KEY` setting that falls back to `SECRET_KEY` when unset, so the signing key can be rotated later without forcing a logout in the same change as a `SECRET_KEY` rotation. Do not add the setting until a human asks for it.
- **pgvector on `db.t3.micro`.** PostgreSQL 15.17 can load `vector`. The instance has 1 GB RAM and is single-AZ. An HNSW index keeps graph data in memory; a large embedding table (1536 dimensions) can push the instance into swap or fail the index build. Phase 7 should start with a small list probe, conservative `m` / `ef_construction`, and "Not configured" when the extension is absent. Move to a larger class before production retrieval traffic.
- **Content Studio (9) shortcuts.** No live social connector (needs company developer apps, Q16) and no metrics refresh. No GPU worker code in this repo (AI team, Q15); the API contract is `/api/v2/workers/*`. Transcripts are pushed to `PUT …/assets/{id}/transcript`; there is no `transcribe` call yet (reuse the meetings route when it lands). Face counts come from the worker; there is no detector here. TTS not configured (Q18). Render GPU seconds are recorded but not yet priced into budgets.
- **Actions and reports (8c/8d) shortcuts.** Room AI threads do not offer tools yet (only buddies). The double-approve guard is a row lock; there is no two-connection test for it yet (the 7g pattern can be reused). Reports have no model polish and list at most 50 rows per section. `meetings.create` does not create a join URL (voice stays behind its flag).
- **BYOK (7k) shortcuts.** One encryption key at a time: a different `CREDENTIALS_KEY_VERSION` makes old keys unreadable until re-entered (add a keyring before the first rotation). Decision 50 `private_only` does not disable external keys yet (no `OrgPolicy` model). Knowledge ask and translation do not take a customer key yet. The key check runs inside the request (up to 20 s); move it to the worker if it hurts.
- **Knowledge ask (7i) shortcuts.** The question's embedding is not written to `UsageEvent` (self-hosted BGE-M3 is a fixed cost today; add `operation=embed` rows if the host bills per token). Backfill lists ids in memory; fine for thousands of sources, page it for millions. On pgvector older than 0.8 the HNSW index filters after scanning, so a small allowed set inside a large org can return fewer than `k` hits (never a forbidden one); RDS 15.17 ships 0.8, so check `SELECT extversion FROM pg_extension WHERE extname='vector'` after `CREATE EXTENSION`. Deleting a room with many chunks deletes vectors one row at a time.
- **Budget spend is computed row by row** (`telemetry.pricing.month_spend`). Fine at today's volume; move to grouped SQL per provider/model/price window when usage grows. The cap is soft: it blocks the next call after spend reaches it.
- **No Redis and no SQS.** Background work stays on PostgreSQL until an infra change is approved.

- **SSO (17c) shortcuts.** SAML 2.0 is not built (needs a library choice and an IdP test tenant). JWKS is fetched per login (no cache); fine at login volume. Only one OIDC connection per org. SCIM supports `userName eq` filtering only, no `/Bulk`, no `/Schemas`; group membership is replaced per PATCH operation, not diffed.

- **17e/17f shortcuts.** The export zip is built in one worker job (spooled to disk over 64 MB) and capped by `EXPORT_MAX_MESSAGES` (`truncated: true` in the manifest); no resumable or per-room export. Impersonation audits every request (one row each); a long support session on a busy page writes many rows. A streaming response opened under impersonation is not cut at expiry. The marketplace has no versioning or update notices for installed copies. Helm chart not linted; no ingress, HPA or PodDisruptionBudget yet.

- **Phase 17 review leftovers.** Stripe `checkout.session.completed` still takes the plan from metadata (fine while no client-side checkout exists; derive it from the price when checkout ships). Impersonation blocks only the known GET side effects (translation, read markers); new GET endpoints with side effects must check `console.impersonation.is_impersonated`.

- **Pulse (13) shortcuts.** Routing is applied to platform calls that don't name a model: primary then fallbacks (allowlisted, at most 3), failing over only when the provider failed; skipped models are recorded as error calls and the trace as `fallback`. At call time it doesn't skip models on last-day health or latency the way the preview does, and the max task cost isn't enforced per call yet. Metrics are computed in Python per request (fine for thousands of events a week; move to SQL aggregates or a rollup table when usage grows). No SSE stream: the console polls. Shadow and canary runs are not built (spec: only after evaluations work).

- **Integrations (15) shortcuts.** Only GitHub (fine-grained token) is live. Google Calendar, Drive, Gmail, Zoom, Discord and Notion need company OAuth apps and are declared "not set up yet". No webhook-driven sync: syncs run when asked. OAuth connectors (Google, Zoom, Notion): the owner will register the apps and add them later, by hand, inside FloBrain.

- **Privacy center (16) shortcuts.** Erasure removes a person's room messages (body cleared, vectors deleted), time descriptions and private AI conversations in one org; document revisions they wrote stay (shared documents), and room AI threads they started stay (shared with the room). "Pinned" recordings (Q20) are not built. Retention deletes at most 50,000 messages per org per run. The product-analytics consent is enforced (no product events). `analytics_personal_only` is stored but hidden from the page until a personal-insight screen exists to honour it. The load test ran on the build machine only (`deploy/loadtest/RESULTS.md`); rerun on staging. Sign-in bursts are CPU-bound (PBKDF2), so size API tasks for them.

- **Meetings (2026-10-21) shortcuts.** The call page polls every 10 seconds for the recording state instead of using LiveKit data messages. Recording is audio only (no video file). Transcripts are not indexed for org search yet. The assistant's page selectors for Meet, Teams and Zoom can't be tested here (no access to those sites from the build machine) and will need a first live run and probably adjustments; it records the mixed meeting audio, so there is no per-speaker labelling. Whisper runs one transcription at a time per replica. Losing room access during a call doesn't remove the person from it (tokens last 10 minutes and rooms can't be recreated, but a connected person stays until they leave or the call ends; add `RemoveParticipant`).

- **Review 10–13 leftovers.** Certificate verification stays public whatever the `public_portfolio` flag says (a verifier must be able to check it); internal project and tag names now appear only when the issuer ticks "include details". The demo still trusts `DEMO_MODE` with a warning (`flobrain.W010`) when `DEBUG` is off. Tauri desktop shell (Phase 10): dropped by the owner on 2026-10-21; the web app installs as a PWA instead.

## Still open (from AUDIT §6 and extras)

| ID | Status |
|---|---|
| D1 | V1 `Role`/`UserRole` still unused; V2 uses `organizations.can()` |
| D6 | V1 chat still has no RAG; image not sent; token fields on `Message` still unwritten. `model` is forwarded (0d). V2 `generate_v2()` added |
| D7 / B11 | Save still freezes to S3 first |
| D8 | Celery/Redis unused in request path; jobs eager locally (0d) |
| D9 remainder | `refresh_tokens` table still unused; V1 signout is Bearer-gated (#250) |
| D10 | Live dashboard (#250); `connected_devices` still 0 |
| D11 / B12 | V1 OpenAPI still weak; V2 declares BearerJWT |
| D12 | Deployed API vs repo (Q30) |
| B1, B2, B4, B6–B11, B14, B16, B19 | See AUDIT; B2 limited to `generate_v2`; B19 `DRF_NUM_PROXIES` readable, unset locally |
| F5 | Frontend i18n: V2 catalogs only; V1 has none |
| P1, P2, P4 | No IaC; migrations-on-ECS unanswered (Q28); backend deploy workflow exists but disabled (0f) |
| P5 | Website still Vercel |
| C1 | Doc attachments: local storage only; S3 presigned uploads not built (501 on ECS) |
| C2 | Tasks are not in knowledge search (their visibility rules differ from rooms); meeting summaries and transcripts are |
| C3 | Content Studio: caption translation, a music control, real TTS, social connectors, GPU worker and face detection wait for Q15, Q16, Q18 |
| C4 | Notion masterclasses refresh on "Sync now" only; no schedule |
| C5 | Leads can't grant permissions to their own team (the matrix allows it; leads don't hold `grants.create`) |
| C6 | Feedback reports carry a written description, no screenshot (no upload storage for it) |
| C7 | Outside agent calls are approved on the External agents page, not the shared Approvals inbox, and proposing one sends no notification yet |
| C8 | Support sessions can still read group rooms (a console test expects it); decide with Q40/Q42 |
| C9 | The task board loads 100 tasks at most (shows a notice when there are more) |
| C10 | Turkish uses informal "sen" throughout; French uses "vous", Portuguese "você". Native speakers should review all three |
| C11 | Helm chart checked with a stand-in renderer only; run `helm lint` and a test install |
| C12 | Expired `SAMLRequest` and `SSOState` rows are never purged |

## Phase 0 shortcuts to revisit

- `PasswordResetToken` lives in `users.0003` (PLAN listed `0004`).
- `next-intl` and `openapi-typescript` not in the website lockfile.
- Full website Vitest suite has pre-existing V1 failures; CI runs a V2/axios slice. Docker CLI is not installed on this machine, so the compose `db` service cannot be started here.
- `UsageEvent.org` / `AITrace.org` nullable so V1 chat can write without an org.

## Pre-existing V1 website Vitest failures (proven on `origin/main`)

Quality pass 2026-10-20: the same **41** tests fail on `origin/main` (worktree at `ecb0a76`, 255 passed / 41 failed / 296 total) and on this branch (271 passed / 41 failed / 312 total). They are V1 screens, not Phases 0–3. CI still runs the V2 slice only.

| File | Test |
|---|---|
| `src/app/error.test.tsx` | Error Component should render Go Home link |
| `src/app/dashboard/Dashboard.test.tsx` | Dashboard Page should render MemoryActivity component |
| `src/app/pricing/pricing.test.tsx` | Pricing Component should open popup when Pro plan button is clicked |
| `src/app/pricing/pricing.test.tsx` | Pricing Component should close popup when close is triggered |
| `src/components/layout/navbar/Navbar.test.tsx` | Navbar Component should toggle mobile menu when hamburger button is clicked |
| `src/components/layout/navbar/Navbar.test.tsx` | Navbar Component should close mobile menu when a link is clicked |
| `src/components/layout/navbar/Navbar.test.tsx` | Navbar Component should render the app navigation links when signed in |
| `src/components/layout/navbar/Navbar.test.tsx` | Navbar Component should mark only the current route as active |
| `src/app/dashboard/components/dashboard-skeleton/DashboardSkeleton.test.tsx` | DashboardSkeleton Component should render Workflow Engine skeleton section |
| `src/app/dashboard/components/dashboard-skeleton/DashboardSkeleton.test.tsx` | DashboardSkeleton Component should render heatmap skeleton with 7 rows |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render the Memory Activity title |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render the subtitle |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render TODAY stat card |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render THIS WEEK stat card |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render TOTAL stat card |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render Usage Heatmap title |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render all 7 days of the week |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render time labels |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render intensity legend |
| `src/app/dashboard/components/memory-activity/MemoryActivity.test.tsx` | MemoryActivity Component should render heatmap with circular indicators |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render the Workflow Engine title |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render subtitle |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render status badges |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render all alert titles |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render component tags |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render timestamps |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render View Details links |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render footer button |
| `src/app/dashboard/components/workflow-engine/WorkflowEngine.test.tsx` | WorkflowEngine Component should render the correct number of alert items |
| `src/app/home/components/features-card/FeaturesCard.test.tsx` | FeaturesCard Component should apply the correct dynamic background color |
| `src/app/home/components/home-skeleton/HomeSkeleton.test.tsx` | HomeSkeleton Component should render 6 feature card skeletons |
| `src/app/home/components/home-skeleton/HomeSkeleton.test.tsx` | HomeSkeleton Component should render 6 application card skeletons |
| `src/app/payment/components/PaymentMethodPage/payment-method-page.test.tsx` | PaymentMethodPage Component should render all Stripe card input elements |
| `src/app/payment/components/PaymentMethodPage/payment-method-page.test.tsx` | PaymentMethodPage Component should show processing state when submitting payment |
| `src/app/payment/components/PaymentMethodPage/payment-method-page.test.tsx` | PaymentMethodPage Component should handle successful payment |
| `src/app/payment/components/PaymentMethodPage/payment-method-page.test.tsx` | PaymentMethodPage Component should display error message on payment failure |
| `src/app/payment/components/PaymentMethodPage/payment-method-page.test.tsx` | PaymentMethodPage Component should handle card element not found error |
| `src/app/profile/components/AccountSecuritySettings/account-security-settings.test.tsx` | AccountSecuritySettings Component should render 2FA section with title and description |
| `src/app/profile/components/AccountSecuritySettings/account-security-settings.test.tsx` | AccountSecuritySettings Component should render 2FA toggle in disabled state by default |
| `src/app/profile/components/AccountSecuritySettings/account-security-settings.test.tsx` | AccountSecuritySettings Component should toggle 2FA to enabled when clicked |
| `src/app/profile/components/ProfileSettings/profile-settings.test.tsx` | ProfileSettings Component should apply destructive styling to delete button |
