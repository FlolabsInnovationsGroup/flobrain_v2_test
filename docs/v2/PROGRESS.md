# FloBrain V2 progress

Updated as each local PR finishes. Nothing is pushed.

## Current

- Branch: `v2/phase-7-ai` (local only, cut from `v2/phase-0-foundation`, not pushed)
- Last finished: **17b** plans, entitlements and Stripe
- Next: **17c** OIDC SSO, then **17d** SCIM (`PHASE_17_PLAN.md`). Phases 8, 9 and 14 reviewed Phase 8 reviewed (`REVIEW_PHASE_8.md`)

## Test counts per phase (backend Django, cumulative)

| PR / phase | Commit | Backend tests after | Added | Notes |
|---|---|---|---|---|
| Discovery | `b0ac71b` | n/a | docs | AUDIT, DECISIONS, OPEN_QUESTIONS, PLAN |
| 0a | `892f76f` | 22 | 22 | Django CI; memory fixture |
| 0b | `e8768ab` | 29 | +7 | P0 hardening |
| 0c | `d4d9e80` | 47 | +18 | Orgs, `can()`, V2 auth |
| 0d | `2357df0` | 54 | +7 | Telemetry, jobs, E28 |
| 0e | `83fd872` | 54 (backend unchanged) | frontend: 3 then | `/w/` shell + F8 |
| 0f | `3f06dce` | n/a | docs | INFRA, RUNBOOK, TECH_DEBT |
| Phase 1 | `73cbcaf` | 61 | +7 | Members, teams, HR |
| Phase 2 | `9834248` | 64 | +3 | Tasks, assign, mission-control |
| Phase 3 | `5ac15fa` / `720d515` | 65 | +1 | Timer, reports, calendar API |
| Quality pass | `4ee2dae` | **75** | **+10** | Allowed/denied per Phase 0–3 key; isolation; timer/HMAC/sign-in |
| MC + access screens | `2ca490d` | 75 | frontend | Mission Control widgets + access requests/grants |
| Phases 4–6 | `e7da479` | **95** | **+20** | Rooms, meetings, docs, tools, search; every new key allowed + denied; isolation |
| Review A security | `857f337` | **102** | **+7** | Isolation, validation, no secrets; denial test per fix |
| Review B stubs | `6c25f07` | **102** | 0 | 501 / flags off; "Not configured" |
| Review C spec gaps | `02aef5f` | **103** | **+1** | Project rooms, room files, Postgres FTS, chat pages |
| Review D smokes | `4e0a465` | **103** | 0 | Playwright smokes; backend count unchanged |
| Production env + voice flag | `886828c` | **106** | **+3** | Boot with the 12 production env names; `voice_video` stays empty |
| Mongo health timeout | `877b6e5` | **107** | **+1** | Missing Mongo is degraded in about 2s |
| Phase 7a provider | `d9d6e88` | **111** | **+4** | Echo is an error; unknown tokens are NULL; V1 send shape unchanged |
| Phase 7b direct client | `21a0c7e` | **118** | **+7** | OpenAI-compatible chat client; mocked HTTP; 4xx is not retried |
| Phase 7c model list | `d933e19` | **120** | **+2** | Registry models for members; providers empty until BYOK |
| Hang-safe tests | `2249168` | **121** | **+1** | Hang timeout + localhost-only sockets; unmocked 1.1.1.1 fails fast |
| Phase 7d room threads | `56bb078` | **127** | **+6** | Private threads; 404 for same-room member and owner; own text only |
| Phase 7e usage read | `a5d2dde` | **130** | **+3** | Member sees own usage; owner sees org; unknown is null not 0 |
| Phase 7f budgets | `80797a53` | **135** | **+5** | PriceTable money cap; platform only; missing tokens estimated |
| Token same-second fix | `f8172073` | **136** | **+1** | `iat_ms` on new tokens; font restored |
| Phase 7g worker | `322d485b` | **150** | **+14** | Claim/commit/run outside txn; SKIP LOCKED proven with two connections; stale requeue; SIGTERM |
| Review fixes 7b/7d/7f | `d4e25b06` | **165** | **+15** | Output price, provider name, full-prompt estimate, budget validation, input/history limits, HTTPS-only direct |
| Phase 7h vector store | `a6b8ba9c` | **183** | **+18** | Embedder interface + HTTP client; pgvector 1024 table; JSON dev store; filter-before-rank search |
| Room access follows membership | `c37bea01` | **188** | **+5** | Leaving a team/project removes room access; owners/admins cannot read DMs they are not in (E37, Q40) |
| Phase 7i knowledge ask | `d767d650` | **214** | **+26** | Chunks + indexing job + backfill; live-access filter before ranking (JSON and pgvector); quoted sources; direct only; assembler `vault_uri` fix |
| Phase 7j live translation | `e696979b` | **223** | **+9** | Direct only, one call per message, cache redone after edit, budget and per-request cap |
| Phase 7k BYOK | `7a6fe8c6` | **243** | **+20** | Encrypted keys, personal-key isolation, org keys for managers, check states, allowlisted HTTPS hosts without redirects, no fallback |
| Phase 7 review fixes | `cbcbc113` | **253** | **+10** | Independent review: team-delete pruning + live membership check, chunk version check, translation race, quoting, BYOK robustness (`REVIEW_PHASE_7.md`) |
| Phase 8a buddies | `2075830e` | **266** | **+13** | Visibility, pins, private threads, V1 cannot open them, direct only, viewer-scoped retrieval, FloLabs seeds |
| Phase 8b Buddy Builder | `932ff3a9` | **274** | **+8** | Private create, creator-scoped sources/tools, lead/admin approval, re-approval after behaviour edits |
| Phase 8c/8d actions + reports | `dcc711e2` | **292** | **+18** | Propose-only tool calls, re-check at approve, run once, audit; cited team reports; cross-org project fix |
| Phase 8e skills + suggestions | `75be4050` | **295** | **+3** | Own vs confirmed skills, lead scope, ranked suggestions limited to assignable people |
| Phase 8f scheduled agents | `63fba5dd` | **305** | **+10** | Cron parser with 15-min floor, run as creator now, pause on loss of access, events once, proposals only |
| Phase 8 review fixes | `9bc87ca9` | **327** | **+22** | Independent review: 14 medium/low findings fixed (`REVIEW_PHASE_8.md`) |
| Phase 9a Content Studio basics | `dc5576df` | **332** | **+5** | Kits/templates (FLOQ), presigned uploads with server keys, own-vs-all projects |
| Phase 9b render workers | `ddc9ac0e` | **337** | **+5** | Hashed worker tokens, per-job URLs only, validated completion, stale requeue, quota |
| Phase 9c EDL + AI clips | `68f6a27b` | **341** | **+4** | Versioned structured edits, no mid-word cuts, captions on the edited timeline, validated AI output |
| Phase 9d consent + publishing | `580ecbdd` | **348** | **+7** | Sandbox end-to-end; consent at approve and publish; hash-pinned approval; single-use OAuth state; AI submits only |
| Phase 9e batches + copy | `17cab5a6` | **351** | **+3** | FLOQ rows → renders, validated per-platform copy, TTS not configured |
| Phase 9 review fixes | `22a545b0` | **361** | **+10** | Consent on render contents, add-only tags, ETag-pinned bytes, conditional approve, OAuth confirm step, DoS fix (`REVIEW_PHASE_9.md`) |
| Phase 14 public API + webhooks + MCP | `e8078896` | **374** | **+13** | PAT lifecycle, same visibility as the app, propose-only MCP writes, SSRF-safe pinned webhooks, sanitized status export |
| Phase 14 review fixes | `b45800ff` | **381** | **+7** | rooms:write scope, webhook deadline + on_commit, claim-once, eager token revocation (`REVIEW_PHASE_14.md`) |
| Phase 17a org policy | `17399a81` | **384** | **+3** | private_only gate on every AI path, external keys disabled on switch |
| Phase 17b plans + Stripe | `97ab948a` | **389** | **+5** | Entitlements AND flags, verified idempotent webhook, platform-admin-only plans |
| Phase 17c/17d SSO + SCIM | `b1997b67` | **398** | **+9** | OIDC with PKCE/nonce/JWKS, verified domains, one-time code, enforced SSO with owner break-glass, SCIM pending-until-mapped |
| Phase 17e/17f export, marketplace, console, sovereign | `a407b550` | **413** | **+15** | Owner-only memory export, frozen-snapshot marketplace, read-only audited impersonation, private-only lock, compose + Helm skeleton |
| Phase 17 review fixes | `c7b28f3a` | **424** | **+11** | V1 SSO bypass, IdP re-pointing, SCIM scope, owner-only keys, forced private V1 chat, Stripe order, login CSRF (`REVIEW_PHASE_17.md`) |
| Demo mode + UI for 8–17 | `8c2bd1cf` | **428** | **+4** | Seat picker and full tour, demo org and model, role-aware shell, 16 new screens; website V2 slice 31 tests |
| Phase 10 cockpit, RTL, PWA | `ae4f0af5` | **435** | **+7** | Saved cockpit modes, Web Push without message text, offline outbox, Arabic shell; website V2 slice 34 tests |
| Phase 11 learning + certificates | `4cb52e2c` | **442** | **+7** | Signed certificates with public verify + QR, answers never sent, pair-only mentor notes, opt-in portfolio |
| Phase 12 leads + commission | `8706b2d1` | **444** | **+2** | Own-leads only, admin-only money changes with audit, summary |
| Phase 13 Pulse | `46e5f52e` | **448** | **+4** | Metrics from records only, deterministic evals, routing preview, once-per-window alerts |
| Phase 15 integrations + meeting bot | `22f45302` | **451** | **+3** | Connector SDK, room-scoped imports, revoke stops sync, GitHub, consent-first bot |
| Phase 16 privacy center + review 10–13 fixes | `1abf5ff1` | **464** | **+13** | What we keep and who sees it, private time descriptions, own-data zip, admin-decided erasure with vectors, owner retention, seat cap, platform onboarding; 17 review fixes (`REVIEW_PHASES_10_13.md`). SQLite 464 OK (5 skipped), PostgreSQL 464 OK; website V2 slice 36 tests |
| Review 15–16 fixes + Arabic screens | `42b1b1ec` | **469** | **+5** | Active onboarded owner, reserved slugs, one locked seat check, erasure of translations, consent enforced, safer `next` (`REVIEW_PHASES_15_16.md`); every workspace screen in Arabic with a coverage test. SQLite 469 OK, PostgreSQL 469 OK; website V2 slice 40 tests |
| Pulse routing applied | `31e1556c` | **472** | **+3** | Primary then allowlisted fallbacks on provider failure only, never for customer keys or explicit models, failed tries recorded as errors |
| Follow-up review fixes | `278b8290` | **473** | **+1** | Case-insensitive member lookup, one seat count, SCIM order, notification detail, wording |
| Meetings: calls, Whisper, own assistant | `c0905513` | **482** | **+9** | Self-hosted LiveKit calls with recording notice, signed webhook, Whisper transcription, summaries to tasks, uploads, our own bot service (3 Node tests) and Whisper service (2 tests) |
| Meetings review fixes | `32334dcd` | **485** | **+3** | 13 findings fixed (`REVIEW_MEETINGS.md`); bot 6 tests, Whisper service 3 tests. SQLite and PostgreSQL 485 OK |
| Load test baseline | `5b8ecd67` | **486** | **+1** | `me/access` 114 → 11 queries; results in `deploy/loadtest/RESULTS.md` |
| Completion round (all areas, demo end to end, SAML, insights, translations) | (this commit) | **757** | **+271** | SQLite and PostgreSQL 16: 757 OK. Website: tsc, eslint, 80 vitest tests OK (all five languages complete). Review in `REVIEW_COMPLETION.md` |

Frontend V2 CI slice (`src/lib/axios*`, `src/i18n`, `src/lib/v2`, `src/components/v2`, `src/app/w`): **27 passed** (was 19 after the quality pass; +8 screen-logic tests for rooms/chat/meetings/docs/tools/search/notifications plus Mission Control and access).

Full website Vitest was last proven at **271 passed / 41 failed / 312** on the quality pass. The same 41 fail on `origin/main`. Not re-run here because local `node_modules` was incomplete (jsdom/`css-tree`); the V2 slice was run with `--environment node` after repairing `jsdom`.

## Stage B local proof (2026-10-20)

### Pre-Phase 4 checks (before new migrations)

```
$ .venv\Scripts\python.exe manage.py check
System check identified no issues (0 silenced).

$ .venv\Scripts\python.exe manage.py makemigrations --check --dry-run
No changes detected
```

### After Phases 4–6

- `manage.py check` → **System check identified no issues (0 silenced).**
- `manage.py makemigrations --check --dry-run` → **No changes detected.**
- **SQLite** (`DB_ENGINE=sqlite`): **Ran 95 tests in 279.398s OK**
- **PostgreSQL 15** on **5433**: **Ran 95 tests in 475.502s OK** — same count, no SQLite/Postgres diffs.
- Docker CLI is still not installed. Postgres is the user-owned cluster at `D:\pgsql15-data`.

### Permission keys added in Stage B

`room.view`, `room.manage`, `announcement.manage`, `notification.view`, `meeting.view`, `meeting.manage`, `docs.view`, `docs.write`, `tools.manage`, `search.use`.

Each key has an allowed path (member default or owner) and a denied path (outsider 403; member 403 when the key is not a member default). Isolation: other team → 404, other org → 403, inactive member → 403. Search does not return another team's rooms or docs.

### Frontend screens for Phases 4–6

| Screen | Path | States + Vitest |
|---|---|---|
| Mission Control | `/w/[org]/mission-control` | metrics, accomplishments, blocker duration, deadline priority, workload drill-down |
| Access | `/w/[org]/settings/access` | pending requests + active grants |
| Rooms sidebar | layout | search, unread, loading/empty/no-access/error |
| Chat | `/w/[org]/rooms/[roomId]` | polling 5s, no translation control (`translate_to` is 501), Decision 13 timestamps |
| Meetings | `/w/[org]/rooms/[roomId]/meetings` | no join URL, recordings list |
| Docs | `/w/[org]/rooms/[roomId]/docs` | versioned save / 409 |
| Notifications | `/w/[org]/notifications` | unread + mark read |
| Search | `/w/[org]/search` | type filter |
| Tools | `/w/[org]/tools` + right rail | defaults + URL validation |

Realtime stays off (Q7): `POST /api/v2/realtime/ticket` is **503** while the flag is off, and **501** if the flag is on without Channels. Files stay on local paths (`/local-uploads/`, `/media/local/`). Join URLs are omitted until a real provider exists (Q2).

## Stage B review proof (2026-10-20, after groups A–D)

- **SQLite** (`DB_ENGINE=sqlite`): **Ran 103 tests in 295.434s OK**
- **PostgreSQL 15** on **5433**: **Ran 103 tests in 327.701s OK** (`--noinput -v 2`, leftover `test_flobrain_db` dropped first). Same count.
- Playwright (`npx playwright test` in `flobrain-website`): **3 passed** (onboarding skeleton, member smoke, owner workspace switch).
- `git diff --diff-filter=D --name-only origin/main`: no deleted files. `public/fonts/fa-solid-600.eot` is present (32,540 bytes).

## Phase 7a proof (2026-10-20)

- **SQLite**: **Ran 111 tests in 281.079s OK**
- **PostgreSQL 15** on **5433**: **Ran 111 tests in 290.084s OK** (`--noinput`). Same count.
- V1 send still returns `usage.total_tokens` as an integer.

## Skipped / defaults used

- Q11, Q12, Q28, Q29, and Q31 are decided and do not block the plan. `system` nodes stay admin-only. The first V2 deploy sets a new `AES_MASTER_KEY` and moves to gunicorn through staging. Migrations use the one-off task. The production signing key is 66 characters.
- Q7 realtime remains off; polling only.
- Q2 / Q14 / Q17: real meeting media and transcription stay deferred. Endpoints return 501 instead of stub text. No AWS, no S3.
- E16a (pgvector): proposed, Phase 7 only.
- No remotes touched (no push, no GitHub PR).

## Phase 7b proof (2026-10-20)

- **SQLite**: **Ran 118 tests in 285.051s OK**
- **PostgreSQL 15** on **5433**: **Ran 118 tests in 294.148s OK** (`--noinput`). Same count.

## Phase 7c proof (2026-10-20)

- **SQLite**: **Ran 120 tests in 283.166s OK**
- **PostgreSQL 15** on **5433**: **Ran 120 tests in 307.589s OK** (`--noinput`). Same count.

## Hang-safe tests (2026-10-20)

- Cause: 7d send tests could miss a mock and wait on `http://35.153.90.219:8000` for 60s each. The suite then printed dots and looked hung.
- Fix: `HangSafeDiscoverRunner` dumps stacks after 20 minutes and blocks non-localhost `connect`. Provider tests mock `get_provider()`.
- Combined working-tree run (includes uncommitted 7d): SQLite **127** in 304.817s, Postgres 5433 **127** in 309.426s.

## Phase 7d proof (2026-10-20)

- **SQLite**: **Ran 127 tests in 304.817s OK**
- **PostgreSQL 15** on **5433**: **Ran 127 tests in 309.426s OK** (`--noinput --parallel 1`). Same count.

## Phase 7e proof (2026-10-20)

- **SQLite**: **Ran 130 tests in 325.546s OK**
- **PostgreSQL 15** on **5433**: **Ran 130 tests in 330.708s OK** (`--noinput --parallel 1`). Same count.

## Phase 7f proof (2026-10-20)

- **SQLite**: **Ran 135 tests in 364.639s OK**
- **PostgreSQL 15** on **5433**: **Ran 135 tests in 376.512s OK** (`--noinput --parallel 1`). Same count.

## Phase 7g proof (2026-10-20, built in a Linux container by Claude)

- Grok's 7g WIP ran the handler inside the claiming transaction, exited `run_jobs` as soon as the queue was empty (a production worker would restart-loop), had no recovery for rows left in `running`, and its "two claims" test used one connection, so it did not prove `SKIP LOCKED`. All four are fixed.
- Also found: `test_password_change_rejects_old_access_token` failed on a fast machine. A token minted in the same second as `password_changed_at` was rejected. Fixed with `iat_ms`.
- **SQLite**: **Ran 150 tests OK** (1 skipped: the Postgres-only SKIP LOCKED test).
- **PostgreSQL 16 + pgvector** (container, port 5433): **Ran 150 tests OK**. Re-run on the Windows Postgres 15 before merging.
- The same suite takes about 15 seconds on Linux and about 5 minutes on Windows. If it feels stuck on Windows, run with `--durations 15` to see the slow tests (likely refused localhost connections to Mongo).

## Next

`v2/phase-7-ai` has 7a–7k and 8a–8f. Next is the Phase 8 review, then Phase 9. Do not push.
