# FloBrain frontend guide

The architecture and rules of `flobrain-website`, for a frontend developer joining the team.
Read it once end to end before your first PR. Every path, name and command here was checked against the code on 2026-10-21.
The backend side (API, permissions, flags, migrations) is in [BACKEND_GUIDE.md](BACKEND_GUIDE.md).

## Contents

1. [What FloBrain is and where the frontend fits](#1-what-flobrain-is-and-where-the-frontend-fits)
2. [Folder map and the V1/V2 boundary](#2-folder-map-and-the-v1v2-boundary)
3. [Data flow: auth, API layer, screen states](#3-data-flow-auth-api-layer-screen-states)
4. [Roles, permissions and feature flags](#4-roles-permissions-and-feature-flags)
5. [Layout and shell](#5-layout-and-shell)
6. [Design system rules](#6-design-system-rules)
7. [Languages (i18n) and RTL](#7-languages-i18n-and-rtl)
8. [Feature areas map](#8-feature-areas-map)
9. [Testing and quality gates](#9-testing-and-quality-gates)
10. [Rules: do and don't](#10-rules-do-and-dont)
11. [How to add a new screen](#11-how-to-add-a-new-screen)
12. [Demo mode on the frontend](#12-demo-mode-on-the-frontend)
13. [Known gaps and tech debt (frontend)](#13-known-gaps-and-tech-debt-frontend)

---

## 1. What FloBrain is and where the frontend fits

FloBrain V2 is a workspace for teams: rooms (chat), meetings, tasks, time, docs and a crew of AI buddies in one "cockpit". AI answers show their sources, and anything an AI wants to change waits for a person's approval. The backend is Django (`flobrain-core/backend`), exposed under `/api/v2/...`. The frontend is one Next.js app, `flobrain-website`, that serves three products side by side:

| Product | Routes | Look | Notes |
|---|---|---|---|
| V1 app and site | `/`, `/home`, `/signin`, `/register`, `/forgot-password`, `/dashboard`, `/dashboardtemplates`, `/profile`, `/settings`, `/memory`, `/pricing`, `/checkout`, `/payment`, `/contact`, `/brain` (route group `src/app/(app)`) | V1 `--fb-*` tokens, V1 navbar and footer | Live product. Must keep working exactly as before. |
| V2 workspace | `/w/signin`, `/w/sso`, `/w/first-login`, `/w/reset-password`, `/w/oauth/consent`, `/w/[orgSlug]/...` | V2 tokens (`.v2-root`) | The team product. Almost all new work lands here. |
| V2 marketing site | `/v2`, `/v2/pricing` | V2 site styles (`.v2-site`) | Static marketing pages. Prices are sample data. |
| V2 public pages | `/p/[slug]` (portfolio), `/p/chat/[siteKey]` (website chat), `/verify/[slug]` (certificate), `/trust/[slug]` (trust page), `/status` (status page) | V2 tokens, signed out | Each page wraps itself in `.v2-root`. |

### Stack and versions

From `flobrain-website/package.json` (installed versions in brackets where the range is open):

| Piece | Version |
|---|---|
| Next.js (App Router, Turbopack) | `^16.2.6` (16.2.6) |
| React / React DOM | `19.2.1` |
| TypeScript | `^5` (5.9.3) |
| Tailwind CSS (via `@tailwindcss/postcss`) | `^4` (4.1.18) |
| Axios | `^1.15.2` |
| Recharts | `^3.7.0` (3.7.0) |
| react-markdown + remark-gfm | `^10.1.0`, `^4.0.1` |
| lucide-react (icons) | `^0.561.0` |
| next-themes | `^0.4.6` |
| class-variance-authority, clsx, tailwind-merge | `^0.7.1`, `^2.1.1`, `^3.4.0` |
| @radix-ui (dialog, label, slot) | `^1.1.15`, `^2.1.8`, `^1.2.4` |
| LiveKit (calls) | `livekit-client 2.22.3`, `@livekit/components-react 2.9.24` |
| Sentry | `@sentry/nextjs ^10.60.0` |
| TanStack React Query | `^5.90.21` (V1 only, see section 3) |
| Vitest / Testing Library / jsdom | `^4.0.18` (4.0.18), `@testing-library/react ^16.3.1`, `jsdom ^27.4.0` |
| Playwright | `@playwright/test ^1.56.1` (1.56.1) |
| ESLint / Prettier | `eslint ^9` with `eslint-config-next 16.0.10`, `prettier ^3.7.4` |

Node: 20 (`flobrain-website/Node.nvmrc` contains `20`, CI uses Node 20, `run-demo.sh` refuses older than 20).

### How to run

**One command, full demo (API + website + sample company).** From the repository root:

```bash
./run-demo.sh        # macOS / Linux
run-demo.bat         # Windows (double-click)
```

It installs Python and npm packages when missing or changed, builds `flobrain-core/backend/demo.sqlite3`, starts the API on `127.0.0.1:8000` and the website on `localhost:3000` with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`, and opens `/w/signin`. Logs go to `.demo-logs/`. Delete `demo.sqlite3` to start clean. Details in [DEMO.md](DEMO.md).

**Website only** (an API already running on port 8000):

```bash
cd flobrain-website
npm ci
npm run dev          # http://localhost:3000/w/signin
```

### npm scripts

| Script | Runs |
|---|---|
| `npm run dev` | `next dev` |
| `npm run build` | `next build` (needs `NEXT_PUBLIC_API_URL`, see below) |
| `npm run start` | `next start` |
| `npm run lint` / `lint:fix` | `eslint src/` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | `vitest` (watch mode; add `-- --run` for one pass) |
| `npm run test:e2e` | `playwright test` |
| `npm run format` / `format:check` | Prettier on `src/**` (do not run `format` across the repo, see section 13) |
| `npm run check-all` | typecheck + lint + format:check |
| `npm run gen:api` | `openapi-typescript ../docs/v2/openapi-v2.json -o src/lib/v2/schema.d.ts` (not usable today, see section 13) |

### Environment variables

Only `NEXT_PUBLIC_*` values reach the browser. Never put a secret in one.

| Variable | Used in | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `src/lib/axios.ts`, `next.config.ts` | API origin. Dev default `http://127.0.0.1:8000`. **Required for production builds**: `next.config.ts` throws when `NODE_ENV=production` and it is unset. |
| `NEXT_PUBLIC_STATUS_JSON_URL` | `src/app/status/page.tsx` | Static status JSON hosted apart from the API. Falls back to `GET /api/public/status`. |
| `NEXT_PUBLIC_SITE_URL` (or `VERCEL_URL`) | `src/lib/site.ts` | Canonical origin for metadata, sitemap, robots. Default `https://www.flobrain.ai`. |
| `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `src/lib/sentry` | Error reporting. |
| `SENTRY_ORG`, `SENTRY_PROJECT`, `SENTRY_AUTH_TOKEN` | `next.config.ts` | Source map upload at build time (server side, not shipped). |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | V1 payment | Stripe publishable key (public by design). |
| `GA_MEASUREMENT_ID`, `NEXT_PUBLIC_LINKEDIN_URL`, `NEXT_PUBLIC_YOUTUBE_URL` | V1 | Analytics and links. |

There is no `.env` file in the repo. Set variables in your shell or a local `.env.local` (ignored).

### Building without internet (font mocking)

The root layout (`src/app/layout.tsx`) uses `next/font/google` (`Inter`), so `next build` downloads font CSS from Google. On a machine without internet the build fails. Next.js reads a mock file from `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` (an internal Next.js variable, see `node_modules/next/dist/compiled/@next/font/dist/google/fetch-css-from-google-fonts.js`). Keep the mock file outside the repo:

```js
// /some/scratch/dir/font-mock.js  (not committed)
module.exports = {
  "https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap":
    `@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;src:url(https://fonts.gstatic.com/s/inter/v1/mock.woff2) format('woff2');}`,
};
```

```bash
cd flobrain-website
NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/some/scratch/dir/font-mock.js \
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run build
```

The V2 fonts (Space Grotesk, JetBrains Mono, IBM Plex Sans Arabic, and Inter on the site) are loaded with a CSS `@import` at the top of `src/styles/v2-tokens.css` and `src/styles/v2-site.css`. That is a runtime request from the browser, so it never blocks a build. Offline, the browser falls back to the next font in the stack.

---

## 2. Folder map and the V1/V2 boundary

All paths are under `flobrain-website/`.

```
messages/
  en.json ar.json tr.json fr.json pt.json   # key catalogs for t("nav.tasks") etc. (V2 shell, auth, demo)
  phrases/{ar,tr,fr,pt}/<area>.json         # screen copy for tr("English sentence"), one file per area
public/
  v2/flobrain-mark*.png  v2/shots/          # V2 brand mark and marketing product shots (2x renders)
  v2/widget.js                              # embeddable website chat widget (channels)
  sw.js  manifest.webmanifest  offline.html # PWA (service worker registered in production only)
e2e/                                        # Playwright specs + global-setup.ts
src/
  app/
    layout.tsx                              # root layout: ThemeProvider, AuthProviderWrapper, ConditionalChrome
    (app)/brain/  dashboard/  profile/ ...  # V1 routes (do not touch for V2 work)
    w/
      layout.tsx                            # PWA metadata for /w
      signin/ sso/ first-login/ reset-password/ oauth/consent/   # signed-out V2 pages
      [orgSlug]/
        layout.tsx                          # WorkspaceGuard > AccessProvider > LayoutProvider > WorkspaceShell
        page.tsx                            # Home (cockpit)
        <area>/page.tsx                     # one folder per screen (78 page.tsx files under /w)
        settings/<area>/page.tsx            # org settings screens
    v2/  layout.tsx page.tsx pricing/       # marketing site
    p/[slug]  p/chat/[siteKey]  verify/[slug]  trust/[slug]  status/   # public V2 pages
  components/
    layout/ConditionalChrome.tsx            # decides V1 navbar/footer or not
    layout/ navbar/ footer/ states/ ...     # V1 components
    v2/
      shell/                                # WorkspaceShell, DemoBar, ProfileMenu, NotificationToaster, icons, BrandMark, AuroraHorizon, ConfirmButton
      screens/                              # core screens + ScreenBody, ToolsRail, WorkspaceHeader, CockpitScreen (RightRail), RoomsSidebar
      ui/kit.tsx  ui/button.tsx             # the V2 kit
      states/                               # Loading, Empty, ErrorState, NoAccess
      <area>/                               # one folder per feature area (ai, automations, billing, bridges, channels,
                                            # compliance, connectors, crew, data, demo, docs, einvoice, evals, growth,
                                            # imports, mcp, memory, platform, rooms, site, studio, tasks, timer, voice)
  lib/
    axios.ts                                # shared Axios instance, token header, refresh on 401 (V1 and V2)
    v2/
      api.ts                                # api.get/post/put/patch/del, apiError, errorText, stateFor, rowsOf, apiClientUpload, publicGet
      client.ts                             # v2Client() typed calls, storeV2Tokens, clearV2Tokens
      auth/WorkspaceGuard.tsx               # signed-in check for /w/[orgSlug]
      access.ts                             # Access type, has, flag, isLead, roleKey, roleLabel, navFor
      AccessContext.tsx                     # AccessProvider, useAccess
      LayoutContext.tsx  layoutRules.ts     # cockpit modes, useLayout, useLowBandwidth, pollEvery, roomTabHref
      useOrgData.ts  useWorkspaceOrg.ts     # data hooks
      demo.ts  sso.ts  home.ts  outbox.ts   # demo sign-in, SSO nonce, safeNext/homePath, offline message queue
      screens/*.ts                          # pure helpers per screen, each with a *.test.ts
      schema.d.ts                           # hand-written minimal OpenAPI types (Me, TokenPair)
  i18n/
    index.ts                                # t(), useLocale(), setLocale(), dirFor(), LOCALES
    phrases.ts                              # tr()/useTr(), translate(), PHRASES merge
    phrases.test.ts  index.test.ts          # translation completeness tests
  styles/
    v2-tokens.css                           # V2 tokens, scoped to .v2-root
    v2-site.css                             # marketing site styles, scoped to .v2-site
```

### ConditionalChrome and the V1/V2 boundary

`src/app/layout.tsx` wraps every page in `ConditionalChrome` (`src/components/layout/ConditionalChrome.tsx`). It renders the V1 `Navbar` and `Footer` around the page, except when the path:

- starts with `/w` (workspace and V2 auth pages),
- is `/v2` or starts with `/v2/` (marketing site),
- starts with `/trust/` (public trust page).

Those bring their own chrome. Other public V2 pages (`/p/...`, `/verify/...`, `/status`) are not in that list, so they render inside the V1 navbar and footer (see section 13).

The two design systems never mix:

- V1 uses `--fb-*` variables and `components/layout/*`, `components/states/*`.
- V2 tokens only exist inside an element with class `v2-root` (`src/styles/v2-tokens.css`). `WorkspaceGuard` renders that wrapper for the workspace; public V2 pages render it themselves. The marketing site uses `.v2-site` (`src/styles/v2-site.css`).
- Import `v2-tokens.css` from the layout or page that needs it (the workspace layout and each public page do this). Never import it from a V1 page.

### Rule: never break V1

Every CHANGELOG entry ends with "V1 behaviour: unchanged". Keep it that way:

- Do not edit files under V1 routes, `components/layout/*`, `components/states/*`, `contexts/AuthContext.tsx`, `lib/api.ts` or `hooks/useApi.ts` for V2 work.
- `src/lib/axios.ts` and `src/app/layout.tsx` are shared by V1 and V2. Change them only with a reason, a test (`src/lib/axios.test.ts`, `src/lib/axios.interceptor.test.ts`), and a check of a V1 page.
- V1 and V2 store their tokens under the same `localStorage` keys (`flobrain_access_token`, `flobrain_refresh_token`). Signing in on one signs you in (or out) on the other.

---

## 3. Data flow: auth, API layer, screen states

### Sign-in and session

Tokens are JWTs kept in `localStorage`. There is no cookie session and no server-side route protection: protection is client-side, and the API enforces everything.

| Step | Code | What happens |
|---|---|---|
| Password sign-in | `src/app/w/signin/page.tsx` -> `v2Client().signin()` | `POST /api/v2/auth/signin`, then `storeV2Tokens()` writes `flobrain_access_token` and `flobrain_refresh_token`. If `must_change_password`, go to `/w/first-login`. Otherwise go to `safeNext(?next=)` or `homePath()` (first org the person belongs to). Error code `sso_required` shows the SSO hint. |
| SSO start | same page, `onSso()` | `GET /api/v2/sso/start?email=&client_nonce=`; `newClientNonce()` stores a random nonce in `sessionStorage` (`flobrain_sso_client_nonce`); the browser goes to `authorize_url`. |
| SSO return | `src/app/w/sso/page.tsx` | `POST /api/v2/sso/exchange` with `code` and `takeClientNonce()` (read once, then removed). Tokens stored with `storeV2Tokens()`. Error codes map to sentences in `SSO_ERRORS` (`src/lib/v2/sso.ts`). |
| Demo sign-in | `src/lib/v2/demo.ts` `demoSignIn(role, landing)` | `POST /api/v2/demo/signin {role}`, stores tokens and `flobrain_demo_role`, returns `/w/<org_slug><landing>`. |
| First login | `src/app/w/first-login/page.tsx` | `v2Client().firstLogin(password)` stores the new token pair. |
| Every request | `src/lib/axios.ts` request interceptor | Adds `Authorization: Bearer <access>` when a token exists. |
| Expired access token | `src/lib/axios.ts` response interceptor | On a 401 (not for `/api/v2/auth/*` or V1 signin/register/refresh), calls `POST /api/auth/refresh/` once with the refresh token, stores the new access token and retries. If refresh fails, both tokens are removed and the original error is returned. |
| Guard | `src/lib/v2/auth/WorkspaceGuard.tsx` | Calls `GET /api/v2/me`. Failure: `clearV2Tokens()` and redirect to `/w/signin?next=<path>`. `must_change_password`: redirect to `/w/first-login`. Personal (non-company) accounts get `NoAccess`. Success renders `<div className="v2-root" dir=...>`. |
| Sign out | `signOut()` in `src/components/v2/shell/ProfileMenu.tsx` | `POST /api/v2/auth/signout {refresh}` (best effort), `clearV2Tokens()` (tokens, the offline outbox `flobrain_outbox_v1`, the push subscription), removes `flobrain_demo_role`, goes to `/w/signin`. |

Redirect safety: `safeNext()` in `src/lib/v2/home.ts` only accepts same-origin paths under `/w/` and rejects `//`, backslashes and whitespace (`src/lib/v2/home.test.ts` has the attack strings). Use it for any `next=` parameter.

### Org resolution and access

`/w/[orgSlug]/layout.tsx` nests the providers in this order:

```tsx
<WorkspaceGuard>                       // signed in? company account?
  <AccessProvider orgSlug={orgSlug}>   // slug -> org id -> GET /orgs/{id}/me/access
    <LayoutProvider>                   // GET/PUT /me/cockpit-layout
      <WorkspaceShell orgSlug={orgSlug}>{children}</WorkspaceShell>
      <NotificationToaster orgSlug={orgSlug} />
    </LayoutProvider>
  </AccessProvider>
</WorkspaceGuard>
```

- `useWorkspaceOrg(slug)` (`src/lib/v2/useWorkspaceOrg.ts`) calls `GET /api/v2/orgs?slug=` and returns `{ orgId, state, error }`. No match gives `no-access`.
- `AccessProvider` (`src/lib/v2/AccessContext.tsx`) loads `GET /api/v2/orgs/{orgId}/me/access` into an `Access` object. On error, `access` stays `null`.
- In any screen: `const { access, orgId, reload } = useAccess();`. `orgId` is `null` until resolved, so every fetch must wait for it (the hooks below already do).

### The API layer (`src/lib/v2/api.ts`)

All V2 calls go through the shared Axios instance (`apiClient` from `src/lib/axios.ts`) with the `/api/v2` prefix added for you.

| Function | Use |
|---|---|
| `api.get<T>(path, params?)` | `GET /api/v2{path}`, returns `data`. `params` is a string map. |
| `api.post<T>(path, body = {})`, `api.put`, `api.patch` | Write calls, return `data`. |
| `api.del(path)` | `DELETE`, returns nothing. |
| `apiClientUpload<T>(path, formData)` | Multipart `POST` with no timeout; the browser sets the boundary. Used for recordings and files. |
| `publicGet<T>(path)` | `GET /api/public{path}` for signed-out pages (portfolio, certificate). |
| `apiError(err)` | Normalises an Axios error to `{ status, code, details }`. `status` 0 means no answer. |
| `errorText(err)` | One sentence for a failed action, ready for a `Notice`. |
| `stateFor(err)` | The `ScreenState` for an error. |
| `rowsOf<T>(value)` | Lists come back as arrays or as `{ results: [...] }`. Always read lists through `rowsOf`. |

`v2Client()` in `src/lib/v2/client.ts` holds older typed helpers (`me`, `orgs`, `tasks`, `rooms`, `roomMessages`, `timer`, ...). New code uses `api.*` directly or `useOrgData`.

V2 does not use React Query. The `QueryClientProvider` in the root layout is there for V1 (`src/hooks/useApi.ts`). Do not mix the two patterns in V2.

### Loading data: `useOrgData`

```ts
const { data, state, error, reload, setData } = useOrgData<T>(orgId, "/packs", { list: true });
```

- Loads `GET /api/v2/orgs/{orgId}{path}`. With `{ orgScoped: false }` the path is used as is (for example `/me/...`).
- Pass `path = null` to skip the call (use it when a flag is off: `flag(access, "buddies") ? "/buddies" : null`).
- With `{ list: true }`, an empty list becomes the `empty` state.
- `reload()` sets `loading` and fetches again. `setData` lets you update after a write without a refetch.

### HTTP status to screen state

`screenStateFromHttp()` in `src/lib/v2/screens/status.ts`:

| HTTP status | `ScreenState` | What the person sees (via `ScreenBody`) |
|---|---|---|
| 2xx with data | `ready` | The screen |
| 2xx, empty list (`list: true`) | `empty` | `Empty` with your `emptyLabel` or "No data yet" |
| 401, 403, 404 | `no-access` | `NoAccess`: "You do not have access" |
| 501 | `off` | "This feature is switched off for your organization. An admin can turn it on." |
| 0 (no answer), other 4xx, 5xx | `error` | `ErrorState` with the server's `details` (or "Something went wrong") and a Retry button |

The backend answers **501 when a feature flag is off** and **403 when the person lacks a permission**. That is why a screen does not need its own flag check to be safe: it just renders `ScreenBody`.

`errorText()` for actions (buttons, forms):

| Status | Sentence |
|---|---|
| 0 | "The server did not answer. Check that the API is running." |
| 403 | server `details`, or "You don't have permission to do this." |
| 404 | "Not found, or you can't see it." |
| 409 with code `private_only` | "Your org only allows self-hosted AI, and none is set up." |
| 429 | server `details`, or "Too many requests. Try again in a minute." |
| 501 | server `details`, or "This feature is switched off for your organization." |
| other | server `details`, or the error code |

Note: `errorText()` returns English. Most screens pass server `details` through as is.

### State components

| Component | File | Notes |
|---|---|---|
| `ScreenBody` | `src/components/v2/screens/ScreenBody.tsx` | Props `state`, `error`, `emptyLabel`, `onRetry`, `children`. Renders the right state or the children. Use it on every screen. |
| `Loading` | `src/components/v2/states/Loading.tsx` | `role="status"`. |
| `Empty` | `src/components/v2/states/Empty.tsx` | Optional `label`. |
| `ErrorState` | `src/components/v2/states/ErrorState.tsx` | `role="alert"`, optional `onRetry`, `retryLabel`. |
| `NoAccess` | `src/components/v2/states/NoAccess.tsx` | `role="alert"`. |

Import them from `@/components/v2/states`, never from the V1 `@/components/states`.

### Cross-screen events

Two `window` events keep the shell in sync without a global store:

- `flobrain:approvals-changed`: dispatch after approving or rejecting an AI action. `WorkspaceShell` listens and recounts the Approvals badge.
- `flobrain:timer-changed`: used by the top-bar timer.

---

## 4. Roles, permissions and feature flags

### The `Access` object

`src/lib/v2/access.ts`:

```ts
type Access = {
  org: { id; slug; name; demo: boolean };
  user_id: string;
  org_role: "owner" | "admin" | "member" | null;
  is_platform_admin: boolean;
  leads_teams: string[];          // team ids this person leads
  permissions: string[];          // effective permission keys, e.g. "room.view"
  flags: Record<string, boolean>; // org feature flags, e.g. { buddies: true }
  demo_role: string | null;       // set only for demo users
};
```

| Helper | Meaning |
|---|---|
| `has(access, perm)` | `perm` is in `access.permissions`. `false` while `access` is `null`. |
| `flag(access, key)` | The org flag is on. `false` while `access` is `null`. |
| `isLead(access)` | Leads at least one team (`leads_teams.length > 0`). "Team lead" is not an org role. |
| `roleKey(access)` | `owner`, `admin`, `lead` or `member` (owner and admin win over lead). |
| `roleLabel(access)` | Translated role name (`demo.roles.<key>`). |

### The server is the source of truth

The client only hides what a person cannot use. Every endpoint checks the permission and the flag again and answers 403 or 501. Client checks are for a clean UI, never for security:

- Never rely on hiding a button to protect data.
- Never compute a permission from `org_role` on the client. Use `has()` with the permission key the backend checks (see [BACKEND_GUIDE.md](BACKEND_GUIDE.md) for the permission and flag lists).
- A screen reached by URL without access still renders `NoAccess` or the "switched off" state through `ScreenBody`.

### How the nav is built

`navFor(slug, access)` returns `NavGroup[]` (`{ label, items: { href, label, icon, badge? }[] }`). `WorkspaceShell` renders it in the sidebar and in the mobile drawer.

- Labels starting with `nav.` are catalog keys (`messages/<lang>.json` > `nav`), rendered with `t()`. Newer entries use English phrases rendered with `tr()`. Both need translations (section 7).
- `icon` is a key of `ICONS` in `src/components/v2/shell/icons.tsx`. Add the icon there first if it is new.
- A group with no items is not shown (AI, Create). Organization is always shown.
- `badge: "approvals"` shows the count of AI actions with status `proposed` (amber pill).
- The active item: Home matches the exact path; others match by prefix.
- `src/lib/v2/access.test.ts` covers what a member, lead, admin and owner see. Update it with every nav change.

### Nav entries (generated from `navFor` in `src/lib/v2/access.ts`)

Routes are relative to `/w/<orgSlug>`. "Lead" means `isLead(access)`. An empty flag column means no flag check on the client.

**Work**

| Label | Route | Flag | Permission |
|---|---|---|---|
| Home | `/` | | none |
| Tasks | `/tasks` | | none |
| Time | `/time` | | none |
| Calendar | `/calendar` | | none |
| Mission Control | `/mission-control` | | `mission.view` |
| Insights | `/insights` | | none |

**Talk**

| Label | Route | Flag | Permission |
|---|---|---|---|
| Rooms | `/rooms` | | `room.view` |
| Inbox | `/notifications` | | none |
| Search | `/search` | | none |
| People | `/directory` | | none |

**AI**

| Label | Route | Flag | Permission |
|---|---|---|---|
| Ask the org | `/ask` | `memory_search` | `knowledge.ask` |
| Buddies | `/buddies` | `buddies` | `ai.use` |
| Approvals (badge) | `/approvals` | `ai_actions` | none |
| Agents | `/agents` | `scheduled_agents` | `ai.use` |
| Team reports | `/reports` | `auto_reports` | lead or `report.generate` |
| Pulse | `/pulse` | `pulse` | `pulse.view` or lead |
| Automations | `/automations` | `automations` | `automations.use` |
| Data | `/data` | `data_buddy` | `data.use` |
| What buddies remember | `/memory` | `buddy_memory` | `ai.use` |
| Buddy evals | `/buddies/evals` | `buddy_evals` | `evals.manage` |
| Buddy quality | `/buddies/quality` | `buddies` and `flo_router` | `pulse.view` or `ai.usage.view` |

**Create**

| Label | Route | Flag | Permission |
|---|---|---|---|
| Content Studio | `/studio` | `content_studio` | `content.use` |
| Marketplace | `/marketplace` | `buddies` or `content_studio` | none |
| Learning | `/learning` | `learning` | none |
| Leads and commission | `/commissions` | `commissions` | none |
| Academy | `/academy` | `academy` | none |
| Industry packs | `/packs` | `packs` | `packs.install` |

**Organization**

| Label | Route | Flag | Permission |
|---|---|---|---|
| Access | `/settings/access` | | `org.members.manage` or `grants.create` or `permission_requests.create` |
| Teams and projects | `/settings/teams` | | `team.manage` or `project.manage` or lead |
| Audit log | `/settings/audit` | | `audit.view` |
| Feedback and analytics (owner/admin) or Your reports (others) | `/settings/feedback` | | any loaded access |
| Customers | `/customers` | `customer_buddy` | `customers.view` or `customers.reply` |
| Channels | `/settings/channels` | `channels` | `channels.manage` or `ai.use` |
| E-invoices | `/einvoices` | `einvoice` | `einvoice.view` |
| MCP and tools | `/settings/mcp` | `mcp_hub` | `mcp.manage` |
| Slack and Teams | `/settings/bridges` | `bridges` | `bridges.manage` |
| Import | `/settings/imports` | `imports` | `imports.run` |
| Compliance | `/settings/compliance` | `compliance` | `compliance.view` |
| Compliance (own items) | `/settings/compliance?tab=mine` | `compliance` | none (when `compliance.view` is missing) |
| Integrations | `/integrations` | `integrations`, or `write_integrations` with a permission | none with `integrations`; `integrations.act` or `integrations.manage` with `write_integrations` |
| Notification settings | `/settings/notifications` | | none |
| Privacy | `/privacy` | | none |
| API and webhooks | `/settings/developer` | | none |
| AI policy | `/settings/ai-policy` | | `policy.manage` or `org.view` |
| AI keys | `/settings/ai-keys` | `byok` | `ai.use` |
| AI usage | `/settings/usage` | | `ai.usage.view` |
| AI budgets | `/settings/budgets` | `budgets` | `budget.view` |
| Billing | `/settings/billing` | | `billing.view` |
| SSO and provisioning | `/settings/sso` | | `sso.manage` |
| Retention | `/settings/retention` | | `org.members.manage` |
| Export | `/settings/export` | | `exports.memory` |
| Support access | `/settings/support-access` | | `audit.view` |
| External agents | `/settings/external-agents` | `external_agents` | `ai.use` |
| Incidents | `/settings/incidents` | `status_page` | `incidents.manage`, or platform admin (no flag needed) |

**Platform** (only when `is_platform_admin`): Console, `/platform`.
**Demo** (only when `demo_role` is set): Guided tour, `/tour`.

Routes that exist but are not in the nav: `/tools` (from the tools rail), `/members/[userId]`, `/buddies/[buddyId]`, `/buddies/requests`, `/data/[datasetId]`, `/einvoices/new`, `/einvoices/[invoiceId]`, `/einvoices/[invoiceId]/print`, `/rooms/[roomId]/...`, `/studio/[projectId]`, `/time/reports`, `/settings/profile`, `/settings/billing/checkout`.

### Checks inside screens

Screens use the same helpers to hide controls, for example `has(access, "buddy.create")` on `/buddies`, `has(access, "customers.reply")` on `/customers`, `flag(access, "voice_notes")` in buddy chat. Same rule: hide, never protect.

---

## 5. Layout and shell

### WorkspaceShell

`src/components/v2/shell/WorkspaceShell.tsx` draws, from the outside in:

1. `DemoBar` on top, only when `access.demo_role` is set.
2. `ToolsRail` (far left, 56 px): brand mark, Mission Control (with `mission.view`), the person's external tools (open in a new tab with `rel="noopener noreferrer"`), "Add tool" link to `/tools`. Hidden below `md`. Hidden in Focus mode.
3. Sidebar (`aside`, 256 px, from `lg`): org name, `navFor` groups, optional `VideoTile` (when `layout.panels.video` and the `voice_video` flag), `RoomsSidebar` (when `layout.panels.rooms`), language picker at the bottom.
4. Top bar: menu button (below `lg`) and `WorkspaceHeader`.
5. `<main>` with the page.
6. `RightRail` (from `CockpitScreen.tsx`, 288 px, from `xl`) when `layout.panels.right_rail`, on every page except Home (Home shows the same widgets itself).

The shell also registers `/sw.js` in production, recounts the Approvals badge on path changes and on `flobrain:approvals-changed`, and calls `usePageViews` (product analytics: one `page.viewed` per screen as a path shape, skipped when the person turned analytics off on the privacy page).

### WorkspaceHeader

`src/components/v2/screens/WorkspaceHeader.tsx`: org switcher (`<select>` from `v2Client().orgs()`), cockpit mode switch (only with the `cockpit` flag, from `sm`), `TopBarTimer`, Search link, theme switch (dark and light, `next-themes`, storage key `flolabs-theme`), `ReportProblem`, `ProfileMenu` (low-bandwidth toggle, sign out).

### Cockpit modes

State lives in `LayoutProvider` (`src/lib/v2/LayoutContext.tsx`), loaded from `GET /api/v2/me/cockpit-layout` and saved with `PUT`. Rules are pure functions in `src/lib/v2/layoutRules.ts` (tested in `layoutRules.test.ts`).

| Mode | `effectiveLayout()` result |
|---|---|
| Default | `DEFAULT_LAYOUT` (rooms panel, right rail, widgets `impact, progress, tasks, approvals, buddies`, default room tab `chat`), keeps the saved accent |
| Focus | No rooms, no video, compact, no right rail, widgets `tasks, approvals`. The tools rail is hidden too. |
| Custom | The saved layout as is. Home shows a "Customize" panel in this mode. |
| Org without the `cockpit` flag | Always Default, and no mode switch |
| Low bandwidth (any mode) | Video panel off; the shell hides all `img` and `video` (`[&_img]:hidden [&_video]:hidden`) |

Hooks:

- `useLayout()` returns `{ cockpit, save, enabled, layout, lowBandwidth }`. Use it in new code.
- `useCockpit()` returns the raw `{ cockpit, save }`.
- `useLowBandwidth()` for components that poll or load media.
- `pollEvery(ms, lowBandwidth)`: four times slower (at least 60 s) on low bandwidth. Use it for any new polling.
- `roomTabHref(orgSlug, roomId, tab)`: a room link opens the saved default room tab (`ROOM_TABS`).
- Accent: a saved `layout.accent` overrides `--fb-v2-accent` and `--fb-v2-accent-strong` on the shell.

### Mobile behaviour

| Width | What changes |
|---|---|
| below `sm` (640 px) | Cockpit mode switch hidden |
| below `md` (768 px) | Tools rail hidden |
| below `lg` (1024 px) | Sidebar hidden; menu button opens it as a modal drawer (`role="dialog"`, `aria-modal`, closes on backdrop or X, closes on navigation) |
| below `xl` (1280 px) | Right rail hidden |

`main` uses `px-4` on phones and `md:px-8` above. Use `min-w-0` on flex children and `flex-wrap` on toolbars so nothing scrolls sideways.

### RTL

- Arabic sets `dir="rtl"` on `.v2-root` (`WorkspaceGuard`, public pages) and on `<html>` (`setLocale`).
- Use logical Tailwind classes: `ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `border-s`, `border-e`, `text-start`, `text-end`. The shell does (`border-e`, `start-0`, `end-3`). Never `ml-`/`mr-`/`left-`/`right-` for layout in V2.
- Charts: reverse the x axis in RTL (`reversed={rtl}` in `ResultChart`, with `rtl = dirFor(locale) === "rtl"`).

---

## 6. Design system rules

Source: [DESIGN.md](DESIGN.md) and `src/styles/v2-tokens.css`. The system is called "mission control": a quiet, precise dark interface with one signature, the aurora horizon.

### Tokens

Use tokens through Tailwind arbitrary values, for example `text-[color:var(--fb-v2-text-muted)]`, `bg-[color:var(--fb-v2-surface)]`, `rounded-[length:var(--fb-v2-radius)]`. Never hard-code a hex value in a V2 component.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--fb-v2-void` | `#05040a` | `#eceaf4` | Tools rail, deepest panels |
| `--fb-v2-page` (`--fb-v2-bg`) | `#08070f` | `#f6f5fb` | Page |
| `--fb-v2-surface` | `#14111f` | `#ffffff` | Cards, rows |
| `--fb-v2-raised` | `#1c1829` | `#f0eef8` | Selected and hovered items |
| `--fb-v2-track` | `#25203a` | `#e3e0ef` | Progress tracks |
| `--fb-v2-text` / `-muted` / `-faint` | `#eeebf7` / `#a29db8` / `#827d9a` | `#14111f` / `#5b5670` / `#6e6984` | Text |
| `--fb-v2-border` / `-border-strong` | white 9% / 16% | ink 10% / 18% | Hairlines |
| `--fb-v2-accent` / `-accent-strong` / `-accent-soft` | `#7c6bff` / `#6a58f5` / 16% | `#5b4ae6` / `#4a39d4` / 10% | Primary actions, links, focus |
| `--fb-v2-magenta`, `--fb-v2-cyan`, `--fb-v2-aurora` | `#cc34ff`, `#00d4ff`, gradient | same | The signature only |
| `--fb-v2-waiting` | `#ffb547` | `#b86e00` | Needs a person's approval |
| `--fb-v2-error` | `#ff4d6d` | `#d1243f` | Blocked, overdue, errors |
| `--fb-v2-success` | `#2bd97e` | `#0f8a4f` | Live, online, done |
| `--fb-v2-radius` | `0.75rem` | | Buttons, inputs |

Light theme: `.light .v2-root` overrides the same roles. Test both themes.

Helper classes in `v2-tokens.css`: `v2-mono` (and every `<time>`), `v2-aurora-text`, `v2-card`, `v2-input`. Focus ring for every element: `:focus-visible` 2 px accent outline.

### Colour roles (strict)

| Colour | Means only | Never for |
|---|---|---|
| Violet (accent) | An action you can take, links, focus | Status |
| Amber (`waiting`) | Waiting for a person's approval (approval cards, pending listings, the Approvals badge, `Button variant="waiting"`, `Badge tone="waiting"`) | Warnings, decoration, a chart series |
| Rose (`error`) | Blocked, overdue, error (`Badge tone="bad"`, `Button variant="danger"`, `ErrorState`, `NoAccess`) | Decoration, a chart series |
| Green (`success`) | Done, live, online (`Badge tone="good"`, `Notice kind="ok"`) | Decoration, a chart series |
| Aurora | Behind the site hero, the final call to action and sign-in (`AuroraHorizon.tsx`) | Anywhere else |

Each buddy keeps one gradient everywhere (`src/components/v2/site/content.tsx`). Every AI answer shows numbered sources. Anything that changes data appears as an amber approval card.

### Typography

- `--fb-v2-font-display`: Space Grotesk, then IBM Plex Sans Arabic, Inter, system. Default for the workspace (15 px, line height 1.55).
- `--fb-v2-font-mono`: JetBrains Mono for timers, scores, counts and metadata (`v2-mono`, `<time>`). Use `tabular-nums` for numbers in tables.
- The marketing site uses Inter for long reading (`.v2-site`).
- Headings have negative tracking (set globally). Page titles: `text-2xl font-semibold tracking-tight` (`PageHeader`).

### Kit components

`src/components/v2/ui/kit.tsx`:

| Component | Use |
|---|---|
| `PageHeader({ title, intro?, action? })` | Every page starts with it: a title, one plain sentence about the page, the main action on the end side. |
| `Section({ title, aside?, children })` | A titled block. |
| `Rows` / `Row` | Lists of records. Rows are the default shape for records. |
| `Field({ label, hint?, children })` | A labelled form control (wraps a `<label>`). |
| `Badge({ tone })` | `neutral`, `waiting`, `good`, `bad`, `accent`, following the colour roles. |
| `Avatar({ name, size })` | Initials. `aria-hidden`, so put the name in text next to it. |
| `Notice({ kind })` | Inline result of an action: `info` (`role="status"`), `ok`, `error` (`role="alert"`). |
| `when(iso)` | Date and time as text (medium date, short time). |

`src/components/v2/ui/button.tsx`: `Button` with `variant` `default` (violet), `ghost`, `outline`, `waiting` (amber), `danger` (rose outline), and `asChild` (Radix `Slot`) to style a `Link`.

`src/components/v2/shell/ConfirmButton.tsx`: a button that asks before it acts (first press shows the question and Confirm, optional reason field). Use it for destructive or irreversible actions.

### Charts

Charts use Recharts. Follow the existing ones: `components/v2/data/ResultChart.tsx`, `components/v2/crew/QualityTrend.tsx`, `components/v2/evals/ScoreTrend.tsx`, `components/v2/ai/PulseViews.tsx`.

- One y axis. Never a second axis; put a different unit in a second chart. (`QualityTrend`: "three counts on one axis, thin lines, legend above, table below.")
- At most three coloured series, from `ResultChart.module.css`: `--data-s0` (accent), `--data-s1` (darkened cyan), `--data-s2` (magenta). More series fold into "Other" in `--data-other` (faint text). Slots follow the series name, not its rank, so colours stay stable (`buildChart` in `components/v2/data/chartData.ts`, `MAX_SERIES = 3`).
- Never use amber, rose or green for a series.
- A legend above the chart (a list with swatches) when there is more than one series.
- Always a table view with every value: a "Show as a table" `<details>` or a toggle. `DataTable` in `ResultChart.tsx` shows the pattern (`role="region"`, `tabIndex={0}`, `<caption>`, `scope="col"`).
- Axis ticks in `--fb-v2-text-muted` at 12 px, grid lines horizontal only in `--fb-v2-border`, no axis line on y.
- Numbers formatted for the locale (`formatValue(value, locale)`), `tabular-nums`.
- Reverse the x axis in RTL.

### Accessibility

- Keyboard: everything works without a mouse. Use real `<button>` and `<Link>`/`<a>`. Drag and drop always has a button alternative (the Kanban card has "Move to {status}" buttons, `tasks/Kanban.tsx`).
- Focus: never remove the `:focus-visible` outline. Modals and drawers need a close button with an `aria-label`.
- ARIA: icon-only buttons get `aria-label` (and `title`); decorative icons get `aria-hidden`. Navs get `aria-label`. Current nav item uses `aria-current="page"`. Segmented controls use `role="radiogroup"`/`role="radio"` with `aria-checked` (see the cockpit switch). Status text uses `role="status"`, errors `role="alert"`, and live updates (messages, timer) use `aria-live`.
- Hidden labels: `sr-only` text for selects and icon controls.
- Reduced motion: `v2-tokens.css` and `v2-site.css` turn off transitions and animations under `prefers-reduced-motion: reduce`. Do not add motion that bypasses it (no JS-driven animation without a check). Motion is limited to one hero sequence and the cockpit flattening on scroll.
- Contrast: WCAG 2.1 AA (spec 10.2). The token pairs are chosen for it; muted text on surface is the floor.

### Responsive

- Mobile first. Grids go from one column to `md:grid-cols-2 xl:grid-cols-3` (see `/packs`).
- No horizontal page scroll. Wide tables go in an `overflow-auto` container.
- Touch: keep controls at least the size of `Button` (`px-3 py-2`).

### Copy style

- Plain words, short sentences. Say what happens and what to do next.
- Sentence case for titles, buttons, labels and nav ("Teams and projects", "Show as a table").
- No em dashes. Use commas or periods. (None of the 3,525 `tr("...")` literals in `src/components/v2` and `src/app/w` has one.)
- No marketing tone in the workspace. `PageHeader` intro is one plain sentence about the page.
- Errors say what went wrong and how to fix it ("Enter your work email first.").
- Approvals and AI: say what will happen before it happens; label demo content as demo.

---

## 7. Languages (i18n) and RTL

Five languages: `en`, `ar`, `tr`, `fr`, `pt` (`LOCALES` in `src/i18n/index.ts`). There are two mechanisms. Use `tr()` for all new screen copy.

### `tr()` / `useTr()`: screen copy (`src/i18n/phrases.ts`)

```tsx
const tr = useTr();
<h1>{tr("Download your data")}</h1>
<p>{tr("{n} messages", { n: count })}</p>
<Badge>{tr("state|Open")}</Badge>
```

- The English sentence is the key. English needs no file; missing lines fall back to English.
- `{name}` placeholders are filled from the second argument.
- Context keys: when one English word means two things, prefix a lowercase context and `|`: `tr("state|Open")` shows "Open" in English and has its own lines in other languages. Contexts in use: `duration`, `mode`, `platforms`, `post`, `presence`, `project`, `render`, `request`, `review`, `room tab`, `state`. The prefix may contain spaces (`room tab|AI`).
- `translate(locale, text, vars)` is the non-hook version.

### `t()`: key catalogs (`src/i18n/index.ts`)

`t(locale, "nav.tasks")` reads `messages/<lang>.json` (top-level groups `workspace`, `auth`, `nav`, `home`, `demo`). Missing keys fall back to English, then to the key. Used by the shell, nav keys, demo bar and guard. `index.test.ts` checks that every English key exists in all four other catalogs. Don't add new groups here; prefer `tr()`.

### Locale storage

- Key: `localStorage["flobrain_v2_locale"]`. `getLocale()` reads it, then `<html lang>`, else `en`.
- `setLocale(locale)` writes the key, sets `<html lang>` and `dir`, then **reloads the page**.
- `useLocale()` returns `en` on the server and the stored locale on the client, so hydration never mismatches.
- `dirFor(locale)` is `rtl` for `ar`, else `ltr`.

### Phrase files and the merge

Each language has one JSON file per area in `messages/phrases/<lang>/<area>.json` (29 areas: `academy`, `ai`, `aiadmin`, `automations`, `billing`, `bridges`, `channels`, `common`, `compliance`, `connectors`, `create`, `crew`, `data`, `docs`, `einvoice`, `evals`, `imports`, `mcp`, `meetings`, `memory`, `people`, `platform`, `privacy`, `rooms`, `settings`, `studio`, `tasks`, `voice`, `work`). Format: `{ "English sentence": "Translation" }`.

`phrases.ts` imports every file and merges them per language with `Object.assign` into `PHRASES` (`AR_PHRASES = PHRASES.ar`). If two areas define the same key, the later one in the `merge(...)` list wins, so keep a key in one area.

### What `phrases.test.ts` enforces

1. Every string literal passed as `tr("...")` in `src/app/w`, `src/app/verify`, `src/app/p` and `src/components/v2` has an Arabic line.
2. Every translation keeps the same `{placeholders}` as the English key, in every language.
3. Turkish, French and Portuguese have every key Arabic has.
4. Context prefixes are dropped in English.

What it does not catch (you must check by hand):

- `tr(variable)` and template literals (`` tr(`project|${p.status}`) ``): only double-quoted literals are scanned. Labels kept in arrays and passed through a variable (room tabs, cockpit modes, nav labels, `KIND_LABEL`) need their phrases added by hand.
- Files outside the four roots: `src/app/status`, `src/app/trust`, `src/app/v2`, `src/lib/v2`. `src/lib/v2/access.ts` nav labels are currently all translated, but nothing tests it.
- Single-quoted `tr('...')` (Prettier is set to double quotes, so keep them double).

### Add a phrase

1. Write `tr("Your sentence.")` in the component.
2. Add `"Your sentence.": "..."` to the right area file in `messages/phrases/ar/`, `tr/`, `fr/` and `pt/`.
3. Run `npx vitest run src/i18n`.

### Add a phrase area

1. Create `messages/phrases/{ar,tr,fr,pt}/<area>.json` (all four).
2. In `src/i18n/phrases.ts`, add four imports (`arArea`, `trArea`, `frArea`, `ptArea`) and append each to the matching `merge(...)` line in `PHRASES`.
3. Run `npx vitest run src/i18n`.

`phrases.ts` is shared by every workstream. Append; never reorder or reformat the import block.

### RTL checklist

- Logical classes only (section 5).
- Directional icons (arrows, chevrons, send) flip in RTL with `rtl:-scale-x-100` or `rtl:rotate-180` (see `timer/WeekPicker.tsx`, `growth/CoachPanel.tsx`).
- Numbers and dates: `formatValue(value, locale)` for chart numbers. `when()` uses the browser locale, not the app language (section 13).
- Arabic text uses IBM Plex Sans Arabic through the font stack.

---

## 8. Feature areas map

Routes are under `/w/<orgSlug>` unless marked. Feature docs are in `docs/v2/features/`. Areas without a feature doc are described in [CHANGELOG.md](CHANGELOG.md) and the phase plans and reviews in `docs/v2/`.

| Area | Route(s) | Main components | Phrase area | Feature doc |
|---|---|---|---|---|
| Home (cockpit) | `/` | `screens/HomeScreen.tsx`, `screens/CockpitScreen.tsx` | `people`, `work` | none |
| Rooms and chat | `/rooms`, `/rooms/[roomId]`, `/rooms/[roomId]/ai` | `rooms/`, `screens/ChatScreen.tsx`, `screens/RoomTabs.tsx`, `screens/RoomsSidebar.tsx` | `rooms` | none |
| Voice notes | room and buddy composers | `voice/` | `voice` | [VOICE.md](features/VOICE.md) |
| Tasks | `/tasks` | `screens/TasksScreen.tsx`, `tasks/` | `tasks` | none |
| Time (Flo Chronos) | `/time`, `/time/reports` | `screens/TimeScreen.tsx`, `timer/` | `tasks` | none |
| Calendar | `/calendar` | `screens/CalendarScreen.tsx` | `tasks` | none |
| Mission Control | `/mission-control` | `screens/MissionControlScreen.tsx` | `tasks` | none |
| Insights | `/insights` | page only | `privacy` | none |
| Meetings | `/rooms/[roomId]/meetings`, `/rooms/[roomId]/meetings/[meetingId]` | `screens/MeetingsScreen.tsx`, `screens/MeetingBotInvite.tsx`, `screens/ActionItemTask.tsx` | `work`, `meetings` | none (see [REVIEW_MEETINGS.md](REVIEW_MEETINGS.md)) |
| Docs | `/rooms/[roomId]/docs`, `/rooms/[roomId]/docs/[docId]` | `screens/DocsScreen.tsx`, `docs/` | `docs` | none |
| Notifications (Inbox) | `/notifications`, `/settings/notifications` | `screens/NotificationsScreen.tsx`, `shell/NotificationToaster.tsx` | `settings` | none |
| Search | `/search` | `screens/SearchScreen.tsx` | `work` | none |
| People and members | `/directory`, `/members/[userId]` | `screens/DirectoryScreen.tsx`, `screens/MemberProfileScreen.tsx` | `people` | none |
| Tools rail | `/tools` | `screens/ToolsRail.tsx`, `screens/ToolsScreen.tsx` | `work` | none |
| Ask the org | `/ask` | page only | `ai` | none |
| Buddies and Flo (crew) | `/buddies`, `/buddies/[buddyId]`, `/buddies/quality`, `/buddies/requests` | `crew/`, `ai/ShareRequestsScreen.tsx` | `ai`, `crew` | [CREW.md](features/CREW.md) |
| Approvals (AI actions) | `/approvals` | page, `ai/ProposalEditor.tsx` | `ai` | none |
| Agents (scheduled) | `/agents` | page only | `ai` | none |
| Team reports | `/reports` | page, `screens/ReportsScreen.tsx` | `ai` | none |
| Pulse | `/pulse` | `ai/PulseViews.tsx` | `ai`, `aiadmin` | none |
| Automations | `/automations` | `automations/` | `automations` | [AUTOMATIONS.md](features/AUTOMATIONS.md) |
| Data buddy | `/data`, `/data/[datasetId]` | `data/` | `data` | [DATA.md](features/DATA.md) |
| Customers (customer buddy) | `/customers`, public `/p/chat/[siteKey]` | `channels/` | `channels` | [CHANNELS.md](features/CHANNELS.md) |
| Channels (WhatsApp, Telegram) | `/settings/channels` | `channels/` | `channels` | [CHANNELS.md](features/CHANNELS.md) |
| Integrations and write-back | `/integrations` | `connectors/` | `connectors` | [CONNECTORS.md](features/CONNECTORS.md) |
| MCP hub | `/settings/mcp`, `/w/oauth/consent` | `mcp/` | `mcp` | [MCP.md](features/MCP.md) |
| Slack and Teams | `/settings/bridges` | `bridges/` | `bridges` | [BRIDGES.md](features/BRIDGES.md) |
| E-invoices | `/einvoices`, `/einvoices/new`, `/einvoices/[invoiceId]`, `.../print` | `einvoice/` | `einvoice` | [EINVOICE.md](features/EINVOICE.md) |
| Buddy memory | `/memory` | `memory/` | `memory` | [MEMORY.md](features/MEMORY.md) |
| Buddy evals | `/buddies/evals` | `evals/` | `evals` | [EVALS.md](features/EVALS.md) |
| Imports | `/settings/imports` | `imports/` | `imports` | [IMPORTS.md](features/IMPORTS.md) |
| Compliance and trust page | `/settings/compliance`, public `/trust/[slug]` | `compliance/` | `compliance` | [COMPLIANCE.md](features/COMPLIANCE.md) |
| Academy | `/academy` | `growth/` | `academy` | [GROWTH.md](features/GROWTH.md) |
| Industry packs | `/packs` | `growth/PackDialog.tsx` | `academy` | [GROWTH.md](features/GROWTH.md) |
| Marketplace | `/marketplace` | `growth/ListingRating.tsx` | `create` | [GROWTH.md](features/GROWTH.md) (ratings) |
| Learning | `/learning` | page only | `create`, `docs` | none |
| Leads and commission | `/commissions` | page only | `create` | none |
| Content Studio | `/studio`, `/studio/[projectId]` | `studio/` | `studio` | none |
| Billing and pricing | `/settings/billing`, `/settings/billing/checkout`, site `/v2/pricing` | `billing/` (`pricing.ts` holds `PRICE_BOOK`), `site/Plans.tsx` | `billing` | [PRICING.md](features/PRICING.md) |
| AI admin | `/settings/ai-policy`, `/settings/ai-keys`, `/settings/usage`, `/settings/budgets` | `ai/AiKeysScreen.tsx`, `ai/UsageScreen.tsx`, `ai/BudgetsScreen.tsx`, `ai/BudgetMeter.tsx`, `growth/AiSeatMeter.tsx` | `aiadmin` | none |
| Access and teams | `/settings/access`, `/settings/teams` | `screens/AccessScreen.tsx` | `people` | none |
| Privacy | `/privacy`, `/settings/export`, `/settings/retention` | pages only | `privacy` | none |
| SSO | `/settings/sso`, `/w/sso` | page only | `settings` | none |
| Audit, support, feedback | `/settings/audit`, `/settings/support-access`, `/settings/feedback` | pages, `shell/ReportProblem.tsx` | `people`, `settings` | none |
| Developer and external agents | `/settings/developer`, `/settings/external-agents` | `platform/` | `platform` | none |
| Incidents and status | `/settings/incidents`, public `/status` | `platform/StatusView.tsx` | `platform` | none |
| Platform console | `/platform` | page only | `platform` | none |
| Profile | `/settings/profile` | page only | `people` | none |
| Guided tour (demo) | `/tour` | page, `demo/DemoPicker.tsx` | `create` | [DEMO.md](DEMO.md) |
| Public portfolio and certificate | public `/p/[slug]`, `/verify/[slug]` | pages only | `create` | none |
| Marketing site | `/v2`, `/v2/pricing` | `site/` | none (English only) | [DESIGN.md](DESIGN.md) |

The phrase area column is where most of that area's copy lives today (computed from the `tr()` literals), which is not always the area's own name; check the file before adding a duplicate. Feature-round rules (flag off by default, works in the demo, approval for every write that leaves FloBrain, V1 untouched) are in [GROWTH_PLAN.md](GROWTH_PLAN.md).

---

## 9. Testing and quality gates

### Unit tests (Vitest)

Config: `vitest.config.ts` (jsdom, globals, `@` alias to `src`), setup `vitest.setup.ts` (jest-dom matchers, a `matchMedia` stub, a `next/navigation` mock, a motion mock).

Where tests live:

- Next to the code, as `*.test.ts` or `*.test.tsx`.
- Pure logic per area: `src/components/v2/<area>/logic.test.ts` (or `<area>.test.ts`), `src/lib/v2/screens/*.test.ts`, `src/lib/v2/*.test.ts`.
- Translations: `src/i18n/phrases.test.ts`, `src/i18n/index.test.ts`.

Prefer pure functions in a `.ts` file with a node-friendly test over rendering a whole screen.

```bash
cd flobrain-website
npx vitest run src/i18n                         # translations
npx vitest run src/lib/v2/access.test.ts        # one file
npx vitest run src/components/v2/data           # one area
npx vitest run -t "navFor"                      # by test name
# The CI slice (same as .github/workflows/website-ci.yml):
npm test -- --run src/lib/axios.test.ts src/lib/axios.interceptor.test.ts src/i18n src/lib/v2 src/components/v2 src/app/w
```

On 2026-10-21 the CI slice ran 50 files, **211 tests, all passing** (about 75 s, most of it jsdom setup).

### Known pre-existing V1 failures

The full suite (`npx vitest run`) has failures in V1 screens that also fail on `origin/main`. They are listed test by test in [TECH_DEBT.md](TECH_DEBT.md) ("Pre-existing V1 website Vitest failures": 41 tests in `src/app/error.test.tsx`, `dashboard`, `pricing`, `navbar`, `home`, `payment`, `profile`). Re-checked on 2026-10-21:

```bash
npx vitest run src/app/profile src/app/dashboard
# Test Files 7 failed | 5 passed (12); Tests 26 failed | 53 passed (79)
```

The 26 match the TECH_DEBT list for those two folders (22 dashboard, 4 profile). One more file, `src/app/profile/components/HelpSettings/help-settings.test.tsx`, fails as a suite with "No test suite found"; it is not in the TECH_DEBT list. Don't fix V1 tests as a side effect of V2 work, and never let a V2 change add a failure to that list.

### End to end (Playwright)

Config `playwright.config.ts`: `testDir: ./e2e`, one worker, base URL `http://127.0.0.1:3000`. It starts `npm run dev` itself and, when `flobrain-core/backend/.venv` exists, the Django API on port 8000 (`reuseExistingServer: false`, so stop `run-demo` first). `e2e/global-setup.ts` runs `migrate` and `seed_v2_demo` on SQLite.

| Spec | What it checks |
|---|---|
| `e2e/onboarding.spec.ts` | `/w/signin` renders a heading (no backend needed) |
| `e2e/workspace.spec.ts` | Sign in, Cockpit and Rooms headings, open the Product room, send a message, Tasks, timer Start, Mission Control denied for a member, owner switches workspace. Skipped without the backend venv. Uses the `flolabs` org from `seed_v2_demo`, not the Nile Labs demo. |

```bash
npx playwright install chromium     # once
npm run test:e2e
```

The specs find elements by role, label and placeholder ("Email", "Password", "Continue", "Write a message", "Send", "Start"). If you rename those, update the specs.

### Static checks and build

```bash
npm run typecheck        # tsc --noEmit (clean on 2026-10-21)
npm run lint             # eslint src/ (clean on 2026-10-21)
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run build
```

ESLint (`eslint.config.mjs`) extends `next/core-web-vitals` and `next/typescript` and adds, among others: `react/no-danger` (error), `@typescript-eslint/no-unused-vars` (error, `_` prefix allowed), `no-explicit-any` (warn), `no-console` (warn, `warn` and `error` allowed), `react-hooks/exhaustive-deps` (warn). V1 test files are ignored; V2 test files (`src/components/v2`, `src/lib/v2`, `src/i18n`, `src/app/w`) are linted.

### Before you open a PR

CI (`.github/workflows/website-ci.yml`, on PRs to `main` and `development` touching `flobrain-website/**`) runs lint, typecheck, the V2 Vitest slice, a build with `NEXT_PUBLIC_API_URL`, and Playwright. Run the same locally:

- [ ] `npm run lint` passes
- [ ] `npm run typecheck` passes
- [ ] The CI Vitest slice passes, including `src/i18n` (all four languages complete)
- [ ] `npm run build` passes (with the font mock if offline)
- [ ] `npm run test:e2e` passes if you touched sign-in, the shell, rooms, tasks or the timer
- [ ] You opened the screen as owner, admin, lead and member in the demo, in dark and light, in Arabic (RTL), and at phone width
- [ ] One V1 page (`/`, `/signin`, `/dashboard`) still looks and works as before
- [ ] No new pre-existing-failure entries

PRs target `development` (`CONTRIBUTING.md`), using `feat/<scope>-<short-desc>` or `fix/<scope>-<short-desc>` branches.

---

## 10. Rules: do and don't

### Security

- **No secrets in the client.** Only `NEXT_PUBLIC_*` reaches the browser, and none of them may hold a secret. API keys, webhook secrets and OAuth client secrets live on the server. Screens that show a secret once (`platform/Secret.tsx`) get it from the API response and never store it.
- **No `dangerouslySetInnerHTML`.** It is not used anywhere in `src/` and `react/no-danger` is an ESLint error. V2 never renders user content as HTML (DECISIONS.md E25).
- **Markdown** goes through `react-markdown` without `rehype-raw`, so raw HTML is not rendered (`components/v2/docs/DocEditor.tsx`, `/academy`). Links in user markdown open with `target="_blank" rel="noopener noreferrer"`.
- **Links from data**: internal workspace paths, or `https://` only. Check scheme before rendering a URL that came from a user or an outside service (example: `components/v2/compliance/logic.ts` drops non-https websites). Every external link: `target="_blank" rel="noopener noreferrer"`.
- **Redirects**: only through `safeNext()` (paths under `/w/`, same origin).
- **Public pages** (`/p`, `/verify`, `/trust`, `/status`, `/v2`) are signed out. They use `publicGet()` or plain public endpoints and must show only what the org or person chose to publish.
- **Client checks never protect anything.** The API decides (section 4).
- **Browser storage**: only the keys already in use (tokens, `flobrain_v2_locale`, `flobrain_demo_role`, `flobrain_outbox_v1`, `flobrain_sso_client_nonce` in sessionStorage, `fb-v2-doc-draft:<docId>`, `flobrain_chat_<site>` in sessionStorage). Anything per person must be cleared on sign-out (`clearV2Tokens`).
- **Approvals**: anything that changes data on behalf of an AI, or leaves FloBrain, is shown as an amber approval and runs only after a person approves.

### Performance

- Load only what the screen shows. Skip calls with `path = null` when a flag is off.
- Polling: `pollEvery(ms, useLowBandwidth())`, clear intervals on unmount, and cancel stale promises (the `let cancelled = false` pattern used across `lib/v2`).
- Respect low-bandwidth mode: no autoplay media; the shell already hides images and video.
- Big lists: paginate on the server; tables show a capped number of rows with a notice (`DataTable` shows 200).
- Images through `next/image` on the site; product shots are pre-rendered in `public/v2/shots`.

### State

- Server data: `useOrgData` or `api.*` in the component. No global store.
- Shared workspace state only through the existing contexts: `useAccess()`, `useLayout()`.
- After a write: `reload()` or `setData()`; dispatch `flobrain:approvals-changed` when an approval changed.
- Local UI state with `useState`. Per-person preferences that must follow the person go to the API (like the cockpit layout), not `localStorage`.

### Naming and files

- One folder per area: `src/components/v2/<area>/`. Components in `PascalCase.tsx`, pure logic in `logic.ts` (or `<area>.ts`) with `logic.test.ts`, shared types in `types.ts`.
- Route folders are kebab-case and match the nav (`/settings/external-agents`).
- Page files are thin when possible: read `orgSlug` and render a screen component.
- Imports through the `@/` alias.
- Use the kit (`PageHeader`, `Rows`, `Badge`, `Button`, `Notice`) before writing new styled elements.

### Shared files: change with care

These files are used by every area. Keep edits small, append rather than reorder, and mention the change in the PR description:

| File | Why it is sensitive |
|---|---|
| `src/lib/v2/access.ts` | The whole nav and role logic. Update `access.test.ts` with it. |
| `src/i18n/phrases.ts` | Every language import and merge. A wrong line breaks every screen's copy. |
| `src/components/v2/shell/*`, `screens/WorkspaceShell` neighbours (`WorkspaceHeader`, `ToolsRail`, `CockpitScreen`, `RoomsSidebar`) | Every workspace page. |
| `src/app/w/[orgSlug]/layout.tsx` | Provider order. |
| `src/lib/v2/api.ts`, `src/lib/axios.ts` | Every request, V1 included. |
| `src/styles/v2-tokens.css` | Every V2 colour. Change roles only with design. |
| `src/components/layout/ConditionalChrome.tsx`, `src/app/layout.tsx` | V1 and V2 chrome. |
| `messages/*.json` | Catalog parity test across five languages. |

### Don't

- Don't edit V1 routes or components for V2 work.
- Don't hard-code colours, fonts or radii in V2.
- Don't use amber, rose or green outside their meaning.
- Don't write user-facing text without `tr()`.
- Don't add a library without a reason in the PR (check the existing stack first: icons are `lucide-react`, charts are Recharts).
- Don't reformat files you did not change (see section 13 about Prettier).

---

## 11. How to add a new screen

### Checklist

1. **Backend first.** Know the endpoint, the permission key and the flag (if any). See [BACKEND_GUIDE.md](BACKEND_GUIDE.md). Confirm what it returns when the flag is off (501) and without permission (403).
2. **Route.** Create `src/app/w/[orgSlug]/<area>/page.tsx` (or `settings/<area>/page.tsx` for org settings).
3. **Components.** Put anything bigger than the page in `src/components/v2/<area>/`. Put pure logic in `<area>/logic.ts` with a test.
4. **Data.** `const { orgId, access } = useAccess();` then `useOrgData(orgId, "/your-path", { list: true })`. Writes with `api.post/patch/del`, errors with `errorText()` in a `Notice`.
5. **States.** Wrap the content in `ScreenBody` with a specific `emptyLabel`.
6. **Layout.** Start with `PageHeader` (title, one-sentence intro, main action). Use `Rows`/`Row`, `Badge`, `Button`. Width: `max-w-3xl` for lists and forms, wider for grids.
7. **Copy.** Every string through `tr("...")`. Add the phrases to `messages/phrases/{ar,tr,fr,pt}/<area>.json`. New area: register it in `src/i18n/phrases.ts` (section 7).
8. **Nav.** Add the entry to `navFor()` in `src/lib/v2/access.ts` with the same flag and permission the backend uses; add the icon to `ICONS` if needed; extend `src/lib/v2/access.test.ts`. If the label is an English phrase, add its translations.
9. **Hide controls** the person can't use with `has()`/`flag()`; the server still checks.
10. **Demo.** The screen should have data in the demo (seeded by the backend). Check it in every seat.
11. **Check** RTL, light theme, phone width, keyboard only.
12. **Gates.** Lint, typecheck, CI Vitest slice, build (section 9).
13. **Docs.** Add or update `docs/v2/features/<AREA>.md` and a line in `docs/v2/CHANGELOG.md` ending with "V1 behaviour: unchanged."

### Minimal example

Trimmed from the real Support access page (`src/app/w/[orgSlug]/settings/support-access/page.tsx`):

```tsx
"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Session = { id: string; user: { email: string }; admin: { email: string }; created_at: string; live: boolean };

export default function SupportAccessPage() {
  const tr = useTr();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Session[]>(orgId, "/impersonations", { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function end(id: string) {
    try {
      await api.post(`/orgs/${orgId}/impersonations/${id}/end`);
      setMessage({ kind: "ok", text: tr("Support access ended.") });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader title={tr("Support access")} intro={tr("When FloBrain support views your workspace as one of your people, it shows here with their reason. Sessions are read-only, last at most an hour, and you can end them.")} />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("FloBrain support has never viewed your workspace.")} onRetry={reload}>
        <Rows>
          {rowsOf<Session>(data).map((s) => (
            <Row key={s.id}>
              <p className="font-medium">{tr("{admin} viewed as {user}", { admin: s.admin.email, user: s.user.email })}</p>
              {s.live ? (
                <Button variant="danger" onClick={() => end(s.id)}>{tr("End now")}</Button>
              ) : (
                <Badge>{tr("Ended")}</Badge>
              )}
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </div>
  );
}
```

When the page is a thin wrapper around a screen component, use the server-component pattern from `src/app/w/[orgSlug]/notifications/page.tsx`:

```tsx
import { NotificationsScreen } from "@/components/v2/screens/NotificationsScreen";

export default async function NotificationsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <NotificationsScreen orgSlug={orgSlug} />;
}
```

Wrap the screen in `<Suspense>` when it reads `useSearchParams()` (see `tasks/page.tsx`).

---

## 12. Demo mode on the frontend

Demo mode is a backend switch (`DEMO_MODE=True`). The frontend only reacts to it. The demo company is Nile Labs, one person per seat. Full backend details and what is seeded: [DEMO.md](DEMO.md).

### Demo picker (`/w/signin`)

- `DemoPicker` (`src/components/v2/demo/DemoPicker.tsx`) calls `demoInfo()` -> `GET /api/v2/demo`. If demo is off (404 or `enabled: false`), it renders nothing, so production sign-in looks normal.
- "Take the full tour" signs in as the owner and lands on `/tour`.
- Each seat (owner, admin, team lead, member) shows `ROLE_HIGHLIGHTS` and `ROLE_INITIALS` from `src/lib/v2/demo.ts` and signs in with `demoSignIn(role)`.

### Demo bar and tour

- `DemoBar` (`src/components/v2/shell/DemoBar.tsx`) shows when `access.demo_role` is set: "Demo workspace. You are the <role>.", a seat switcher (signs in as the other role), Guided tour, and Start over (`demoReset()` -> `POST /api/v2/demo/reset`, then signs in again with the same role).
- The nav gets a Demo group with Guided tour (`/tour`).
- `/w/[orgSlug]/tour/page.tsx` holds `STOPS`: numbered stops, each with the seat to use, a path and what to try. Changing seats from a stop signs in again.
- `usePageViews` receives `access.org.demo`.

### What is simulated

Simulation happens on the server; the frontend shows demo-only controls when the API says the object is a demo one:

| Feature | Frontend piece | What it does |
|---|---|---|
| Calls | `DemoCall` in `rooms/[roomId]/meetings/[meetingId]/page.tsx` | Room members appear as tiles and take turns speaking; recording makes a sample transcript by speaker |
| Meeting assistant | `screens/MeetingBotInvite.tsx` | The backend walks through join, lobby, record in about 40 s |
| WhatsApp, Telegram, customer chat | `channels/DemoSimulator.tsx` | "Pretend a message arrived" (`POST /channels/demo/simulate`) for connections marked `demo` |
| Slack and Teams | `bridges/DemoMention.tsx` | A mention run end to end, approval buttons that work (`/bridges/demo/simulate`, `/bridges/demo/decide`) |
| Webhooks | `platform/DemoInbox.tsx` | A built-in receiver; hidden unless the API reports `demo` |
| SSO | `/w/signin` "Sign in with SSO" | Demo identity provider for `owner@demo.flobrain.example` |
| AI answers, renders, voiceover, social posts, billing checkout | regular screens | Clearly labelled demo results from the server |

Rules: demo-only UI must check the API's `demo` marker, never a hard-coded org slug, and every simulated result must say it is a demo.

---

## 13. Known gaps and tech debt (frontend)

Things that are unclear, inconsistent or unfinished. Fix them deliberately, not as a side effect.

**Auth and session**

- The Axios interceptor refreshes V2 tokens through the V1 endpoint `POST /api/auth/refresh/`. The V2 endpoint `POST /api/v2/auth/refresh` exists in the backend (`users/v2/urls.py`) but the frontend never calls it. Both decode the same token type, but they are separate code paths with different error codes.
- V1 and V2 share the `localStorage` token keys, so one product's sign-in or sign-out affects the other.
- Tokens are in `localStorage` (readable by any script on the origin). Acceptable only because no user HTML is ever rendered.
- Sign-out does not remove doc draft backups (`fb-v2-doc-draft:<docId>` in `localStorage`, `src/lib/v2/screens/docs.ts`); they survive on a shared browser.
- `WorkspaceGuard` redirects to `/w/signin?next=/w` as a fallback, but there is no `src/app/w/page.tsx`.

**Spec versus build**

- Spec 10.3 (`FLOBRAIN_V2_CURSOR_PROMPT.md`) asks for TanStack Query, a client generated from OpenAPI, react-hook-form with zod, and flags from `GET /me`. What was built: `useOrgData` and `api.*`, a hand-written `schema.d.ts`, plain controlled forms, flags from `GET /orgs/{id}/me/access`. Follow the code.
- `npm run gen:api` cannot run: `docs/v2/openapi-v2.json` does not exist and `openapi-typescript` is not installed (TECH_DEBT.md, "Phase 0 shortcuts"). `next-intl` is also not installed; the i18n is home-made.
- Spec 10.3 mentions sanitizing markdown with DOMPurify or rehype-sanitize. Neither is installed; safety relies on react-markdown not rendering raw HTML (AUDIT.md F13).

**Layout and chrome**

- `ConditionalChrome` excludes `/w`, `/v2` and `/trust/` but not `/p`, `/verify` or `/status`, so those V2 public pages render inside the V1 navbar and footer. Unclear if intended.
- `RightRail` is hidden below `xl`, and there is no drawer for it on smaller screens (spec 10.1 says rooms and the right rail become drawers on mobile; rooms do, the right rail does not).

**i18n**

- `phrases.test.ts` only checks double-quoted literals in four folders. Variable labels, template-literal context keys, `src/lib/v2/access.ts`, `src/app/status`, `src/app/trust` and `src/app/v2` are not checked.
- `errorText()`, `SSO_ERRORS` and many server `details` are English only.
- `when()` in `kit.tsx` formats dates with the browser locale (`toLocaleString(undefined, ...)`), not the chosen app language.
- The marketing site (`/v2`) is English only.
- Arabic has 4,329 phrase lines across files, the other three 4,324: a few keys are defined in more than one area file. The merge keeps the last one.
- CHANGELOG.md mentions `messages/ar-phrases/`; the files now live in `messages/phrases/<lang>/`.
- Turkish uses informal "sen", French "vous", Portuguese "você"; native review is pending (TECH_DEBT.md C10).

**Quality**

- Prettier is configured (`.prettierrc`, print width 100) but not enforced in CI. On 2026-10-21, `prettier --check` reported 307 V2 files as not formatted, so `npm run check-all` fails. Don't run `npm run format` across the repo in a feature PR; it would rewrite hundreds of files.
- The full Vitest suite has the pre-existing V1 failures (section 9) plus `help-settings.test.tsx` with no suite. CI runs only the V2 slice.
- Playwright covers sign-in and a few workspace smokes only. Feature rounds (growth, market) have no e2e specs.
- `flobrain-website/` contains three empty stray files: `tsc`, `memory-graph`, `flobrain-website@0.1.0`. The Node version file is `Node.nvmrc`, which `nvm` does not pick up automatically (it reads `.nvmrc`).

**Other**

- Offline builds need the undocumented `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` variable (section 1). It is a Next.js internal and may change.
- V2 fonts load from Google Fonts at runtime through CSS `@import`; there is no self-hosted copy.
- Site prices and the AI-per-seat numbers are sample data until pricing is decided (DESIGN.md, PRICING.md).
- The task board loads 100 tasks at most (TECH_DEBT.md C9).
- `README.md` in `flobrain-website` documents the V1 React Query pattern only; it does not describe V2.
