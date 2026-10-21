# FloBrain V2 progress

Updated as each local PR finishes. Nothing is pushed.

## Current

- Branch: `v2/phase-7-ai` (local only, cut from `v2/phase-0-foundation`, not pushed)
- Last finished: **7f** PriceTable and platform budgets
- Next: **7g** PostgreSQL job worker

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
| Phase 7f budgets | (this commit) | **135** | **+5** | PriceTable money cap; platform only; missing tokens estimated |

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

## Next

`v2/phase-7-ai` has 7a–7f. Next is 7g (PostgreSQL job worker). 7h–7k stay unbuilt. Do not push.
