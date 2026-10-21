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
- **No Redis and no SQS.** Background work stays on PostgreSQL until an infra change is approved.

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
