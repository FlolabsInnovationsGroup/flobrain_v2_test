# Review: Phase 7d to 7g (built while Cursor ran on a smaller model)

Date: 2026-10-20. Reviewer: Claude (Opus 5.5), in a Linux container with PostgreSQL 16 + pgvector on port 5433. Branch `v2/phase-7-ai`, local only, not pushed.

Scope: commits `56bb0781` (7d room threads), `a5d2dde5` (7e usage), `80797a53` (7f budgets), `22491687` (hang-safe tests) and the 7g WIP `4b30fe2f`. The aim was to find security, isolation and correctness gaps before 7h.

## Findings and fixes

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Auth (Phase 0) | A token minted in the same second as `password_changed_at` was rejected (`iat` is whole seconds), so a sign-in right after first-login or a reset could 401. The test `test_password_change_rejects_old_access_token` failed on a fast machine. | High (user-facing) | **Fixed** `f8172073`: new tokens carry `iat_ms`. Tokens without it are compared at the start of their second. Regression test added. |
| 2 | Repo | The 7g WIP commit deleted `public/fonts/fa-solid-600.eot` (`git add -A` picked up a working-tree deletion). | Medium | **Fixed** `f8172073`: restored. |
| 3 | 7g worker | The handler ran inside the claiming transaction, so a slow job held a row lock and an open transaction. | High | **Fixed** `322d485b`: claim commits first; the handler runs outside any transaction (tested). |
| 4 | 7g worker | `run_jobs` exited as soon as the queue was empty, so an ECS worker service would restart-loop. | High | **Fixed**: it polls until SIGTERM/SIGINT; `--once`, `--max-jobs`, `--max-seconds` and `--exit-when-idle` stop it earlier. |
| 5 | 7g worker | A row left in `running` by a crashed worker stayed there forever. | Medium | **Fixed**: `requeue_stale()` after `JOBS_STALE_SECONDS`, called by the worker loop. |
| 6 | 7g tests | The "two claims" test used one connection, so it never exercised `SKIP LOCKED`. | Medium | **Fixed**: a `TransactionTestCase` with a second real connection holding a lock; the claim skips that row (Postgres only, bounded joins). |
| 7 | 7g queue | Without a worker, `enqueue` still created rows that would never run. | Low | **Fixed**: `JOBS_WORKER_ENABLED` (default off). Off means no row and `unavailable`. |
| 8 | 7f pricing | Cost used only `input_price × total_tokens`; `output_price` was ignored. | High (wrong money) | **Fixed**: input × input price + output × output price. A total without a split uses the higher price, so budgets never under-count. |
| 9 | 7f pricing | Usage rows stored `provider=""`, so price lookups could never match a real provider. | Medium | **Fixed**: `ProviderResult.provider` (`multimodal_legacy`, or `AI_DIRECT_PROVIDER` for `direct`) is written to `UsageEvent.provider`. |
| 10 | 7d/7f estimate | Missing tokens were estimated from the new user message only, not from the whole prompt and the reply. | Medium | **Fixed**: input is estimated from the full prompt, output from the reply. Measured values are never overwritten. |
| 11 | 7f API | `PUT /budgets` accepted any value; non-numbers crashed with 500. | Medium | **Fixed**: decimal in [0, 100,000,000], finite, 3-letter currency; otherwise 400 (tested). |
| 12 | 7d cost/abuse | No limit on message length; the whole thread history went to the provider on every send. | Medium | **Fixed**: `AI_MAX_INPUT_CHARS` (default 8000) → 400 before the provider; history bounded to `AI_THREAD_HISTORY_MESSAGES` (default 40) newest messages (tested). |
| 13 | 7b direct | A plain `http://` base URL to a remote host was accepted, so a key could travel unencrypted. | High | **Fixed**: HTTPS required, except `http://localhost`/`127.0.0.1` for local dev. A remote `http://` base is `not_configured` and opens no socket (tested). |

## Checked and fine

- 7d privacy: a thread is filtered by `org`, `user` and `room`, and the room is re-checked with `user_can_access_room` on every read and send. Same-room members and owners get 404 (existing tests). V1 chat views exclude room threads (`room IS NULL`).
- 7d prompt: only the thread's own messages plus a fixed system line. No room messages, tasks, docs or memory (existing test asserts another member's room message is absent).
- 7d echo: the legacy "Echoing input" body is a `provider_error` and is never stored.
- 7e: members see only their own usage rows; owner/admin see the org; unknown tokens are `null` with `token_state: "unknown"`.
- Hang-safe runner: the watchdog and the localhost-only socket guard work.

## Not changed (noted)

- `month_spend` prices row by row. That is fine at today's volume. Move it to grouped SQL when usage grows (TECH_DEBT).
- The budget check is a soft cap: it blocks the next call once spend reaches the cap, and does not reserve the cost of the call in flight.

## Proof

- SQLite: 165 tests OK (1 skipped: the Postgres-only SKIP LOCKED test).
- PostgreSQL 16 + pgvector (container): 165 tests OK.
- `makemigrations --check`: no changes. Re-run both suites on the Windows Postgres 15 (port 5433) before merging.
