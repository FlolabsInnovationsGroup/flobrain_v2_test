# Phase 7 plan

Status: **approved through 7e** (2026-10-20), with the amendments in this file. 7a is built. 7f and later stay unbuilt until each one is reviewed. Branch: `v2/phase-7-ai`. No AWS changes. No push.

Each PR runs the Django suite on SQLite and on Postgres 15 at port 5433 with `--noinput`. V1 `POST /api/brain/chats/<id>/send/` keeps its current status codes and JSON shape.

A feature flag that is off returns **501** with `{"error": "not_implemented", "details": "..."}` (Decision E36). That is the convention for every new Phase 7 endpoint. The already-shipped realtime ticket stays 503 while its flag is off.

## Legacy vs `direct`

`AI_PROVIDER_BACKEND` defaults to `multimodal_legacy` (E29). New V2 AI features use `direct`. `multimodal_legacy` is allowed in V2 only for room threads (7d), and only for the asking user's own text. Room messages, tasks, docs, and memory are never added to that prompt. The host is plain HTTP, unauthenticated, in another account, and caches replies across users.

| | `multimodal_legacy` in V2 | `direct` (7b) |
|---|---|---|
| 7d thread, the user's own text only | Allowed | Default when configured |
| Translation (7j), retrieval (7i), embeddings (7h), key checks (7k) | Never | Required. If `direct` is not configured, the feature stays 501 or "Not configured" and does not call legacy. |
| Org documents, memory chunks, images, other members' text | Do not send | Yes, and only over `direct` |
| OpenAI failure | HTTP 200 echo. V2 treats it as `provider_error` and does not store it. V1 shape stays. | Real status codes |
| BYOK or any credential | Never | HTTPS only, and never to the multimodal host |

Production does not select `direct` until the platform provider key is in Secrets Manager (`INFRA_CHANGES.md`). Tests mock HTTP. The same client talks to a self-hosted OpenAI-compatible server (vLLM or Ollama, Q25) by changing base URL and model in config.

## 7a — Provider interface and unknown tokens

Built on this branch. No new HTTP endpoint.

| | |
|---|---|
| Files | `brain/llm/providers.py`, `brain/llm/base.py`, `brain/llm/multimodal_adapter.py` (V1 `generate()` still returns the raw `result` text), `telemetry/writers.py`, `telemetry/models.py` |
| Migrations | `telemetry/0002_token_counts_nullable`. Null means unknown. V1 rows still store the integer they store today, including `0` when the service omits the field. |
| Endpoints | None. |
| Permission keys | None. |
| Flags | None. `AI_PROVIDER_BACKEND` defaults to `multimodal_legacy`. |
| Tests | Legacy maps the echo body to `provider_error` and does not return it as the V2 reply. A response with no token fields records null, not 0, on the V2 writer. V1 send still returns 200 and `usage.total_tokens` as an integer. `direct` is not selected when the setting is missing, and the stub does not open a socket. |
| Does not | The real `direct` HTTP client, room AI, memory, BYOK, budgets, or a change to the V1 view. |

## 7b — Real `direct` client

Immediately after 7a. Without this, retrieval (7i) cannot answer.

| | |
|---|---|
| Files | `brain/llm/direct.py` |
| Migrations | None. |
| Endpoints | None. |
| Permission keys | None. |
| Flags | None. Selected only when `AI_PROVIDER_BACKEND=direct` and the platform key setting is present. Missing key → `not_configured`, no network. |
| Tests | Mocked HTTP only. Structured `messages[]` are sent. Model must be on the allowlist in config; anything else is rejected locally. Token counts are read from the response. 4xx maps to the V2 error codes (`invalid`, `invalid_credential`, `rate_limited`, `provider_rejected`) and is not retried. Timeout and 5xx map to `provider_unavailable`. A second base URL (the self-hosted shape) is only a setting change. |
| Does not | Call a live provider. Select `direct` in production. Send org files through `multimodal_legacy`. |

## 7c — Model list

| | |
|---|---|
| Files | `brain/v2_views.py` |
| Migrations | None. |
| Endpoints | `GET /api/v2/orgs/{org}/ai/models` |
| Permission keys | `ai.use`. Allowed: active member. Denied: outsider 403, inactive 403. |
| Flags | None. The list is readable without `room_ai`. |
| Tests | Platform models come from the model registry. Providers with an active key for **this user** are included only when that key exists (empty until 7k). Another member's personal key is absent. No secret in the body. |
| Does not | Call a provider. |

## 7d — Room text threads

Flag `room_ai` default off → 501.

| | |
|---|---|
| Files | `brain/models.py`, `brain/v2_views.py`, website room AI tab behind the flag |
| Migrations | `brain/0003_chat_org_room`. V1 querysets keep `room IS NULL`. |
| Endpoints | `GET/POST /api/v2/orgs/{org}/rooms/{room}/ai/threads`, `GET /api/v2/orgs/{org}/ai/threads/{thread}`, `POST /api/v2/orgs/{org}/ai/threads/{thread}/send` |
| Permission keys | `ai.use`. Allowed: the thread owner, who is an active member of that room. Denied: outsider 403, inactive 403, other team's room 404. |
| Flags | `room_ai` default off. |
| Throttle | Per user, `FLOBRAIN_V2["AI_SEND_RATE"]` (default `30/min`) on send. Over the limit → 429. |
| Prompt | The user's own thread only. No room messages, tasks, docs, or memory. A test asserts another member's room message is absent from the provider body. |
| Tests | Decision 12: another member of the **same** room cannot list, read, or send to my thread (404). An owner or admin cannot read the thread body through this API either (404). Echo text is not stored. Tokens follow 7a. Flag off → 501. V1 chat list still hides `room` threads. |
| Does not | Retrieval, citations, images, documents, BYOK, or budgets. The website tab stays off this PR so the room page does not gain a control while the flag is off. |

## 7e — Usage read

| | |
|---|---|
| Files | `telemetry/v2_views.py` |
| Migrations | None. |
| Endpoints | `GET /api/v2/orgs/{org}/usage` |
| Permission keys | `ai.usage.view`. Owner and admin see the org. A member sees only their own rows (Decision 49). Outsider 403. Inactive 403. |
| Flags | None. |
| Tests | Own org only. A member does not see another member's rows. Null tokens are `null` with `token_state: "unknown"`, never `0`. `estimated=true` is `token_state: "estimated"`. No secrets. |
| Does not | Compute prices. That is 7f. |

## 7f — Price table and platform budgets

Decision 49. The budget unit is **money**, from `PriceTable`, not a raw token count.

| | |
|---|---|
| Files | `telemetry/models.py` (`PriceTable`, `Budget`), `telemetry/pricing.py` |
| Migrations | `telemetry/0003_price_and_budget` |
| Endpoints | `GET/PUT /api/v2/orgs/{org}/budgets`, `GET /api/v2/orgs/{org}/budgets/status` |
| Permission keys | `budget.manage` for PUT (owner, admin). `budget.view` for GET. Member 403. Outsider 403. |
| Flags | `budgets` default off → 501, and no enforcement. |
| Rules | `PriceTable` is versioned per provider and model: input price, output price, `valid_from`. Cost uses the row valid at the call. When the provider returns no tokens (legacy today), estimate with a tokenizer, store the estimate, and set `estimated=true`. Never store or show `0` as if it were a measurement. Budgets apply to `credential_source=platform` only. A customer/BYOK call is never blocked and never priced as platform spend. |
| Tests | Over-cap platform call rejected when the flag is on. Customer call ignored by the cap. Missing tokens become an estimate, not 0. Member 403. |
| Does not | Charge a card. Store bank details. |

## 7g — PostgreSQL job worker

E17. Before any indexing.

| | |
|---|---|
| Files | `jobs/models.py`, `jobs/worker.py`, `jobs/management/commands/run_jobs.py` |
| Migrations | `jobs/0002_queue` (the 0001 telemetry-style jobs stub stays). A `jobs` row: kind, payload, status, run_after, attempts, locked_at, last_error. |
| Endpoints | None. Command: `manage.py run_jobs`. |
| Permission keys | None. |
| Flags | None. |
| Production | Its own process: a separate ECS service or task (`INFRA_CHANGES.md`). Until that process exists, job-backed features report "unavailable" (E17). The web process does not run the queue. |
| Tests | Two workers: `SELECT … FOR UPDATE SKIP LOCKED` so only one runs a row. A failing job retries with backoff. A success is not run again. SQLite has no `SKIP LOCKED`; that test runs on Postgres and is skipped on SQLite. |
| Does not | Call Redis, SQS, or Celery. Index content. Apply the ECS change from this branch. |

## 7h — Vector store

E16a. BGE-M3 is **1024** dimensions.

| | |
|---|---|
| Files | `knowledge/store.py`, `knowledge/embeddings.py` |
| Migrations | `knowledge/0001_pgvector`. Read `pg_available_extensions` first. Run `CREATE EXTENSION IF NOT EXISTS vector` only when that row exists. If it does not, record "unavailable" and continue. Do not issue a statement that aborts the migration transaction. SQLite skips the SQL. One table (or one vector column) per dimension so each HNSW index is fixed-width. BGE-M3 uses the 1024 table. A different model or dimension does not share that index. Every chunk row stores model name and dimension. |
| Endpoints | None. |
| Permission keys | None. |
| Flags | `memory_search` default off. Missing extension or flag off → the feature reports "Not configured". |
| Embeddings client | OpenAI-compatible `POST {base}/v1/embeddings`. Config is base URL, model name, and expected dimension, so BGE-M3 on JarvisLabs (vLLM, TEI, or similar) is a config change. A response whose vector length differs from the configured dimension is rejected and not stored. Missing config → "Not configured" and no network. Tests mock HTTP. |
| Tests | Deterministic fake embedder, 1024 floats, model name stored. The HTTP client is mocked: a wrong dimension is rejected; a missing base URL does not open a socket. Round-trip on Postgres when `vector` is available. Suite stays green when it is not. |
| Does not | Download BGE-M3. Turn the flag on. Index org content. Call a live embeddings server. |

## 7i — Retrieval before ranking

Decision 12 and Decision 32. Answers go through `direct` (7b). If `direct` is not configured, the ask returns "Not configured" and does not call `multimodal_legacy`.

| | |
|---|---|
| Files | `knowledge/index.py`, `knowledge/retrieve.py`, `knowledge/views.py`, `memory/context_assembler.py` |
| Migrations | `knowledge/0002_chunks` (org, room, team, source type, source id, model name, dimension). Vectors live in the dimension table from 7h. |
| Endpoints | `POST /api/v2/orgs/{org}/knowledge/ask` |
| Permission keys | `knowledge.ask`, default for members who have `search.use`. Outsider 403. Inactive 403. |
| Flags | `memory_search` stays off in production until embedding hosting is approved. Off → 501, no embedder call. |
| Indexing | Enqueued on the 7g worker. `manage.py index_knowledge --org <id>` enqueues existing docs and messages. Idempotent by content hash. If the worker process is not running, the feature reports "unavailable". |
| Prompt | Retrieved text goes into the prompt as quoted data with its source, never as instructions. The system prompt says so. |
| Live permissions | At query time, check the asker's **current** room and team membership and inactive status against the source. Stored metadata is not enough. |
| Deletes | Deleting a doc or a message deletes its chunks. The query also drops a source that no longer exists. |
| Assembler bug | `context_assembler._fetch_node_payload` calls `retrieve_from_cold_storage(node)`. That function expects a vault URI string (`s3://…`). Passing the node raises, the error is swallowed, and the S3 object is never read. 7i passes `node.metadata.get("vault_uri")` and, when that is missing, uses the plaintext metadata already on the row. |
| Tests | Fake embedder. Another team's doc and another org's doc never appear in the prompt or the citations. A user removed from the team stops seeing that team's chunks on the next ask. A deleted doc or message is absent. Flag off → 501 and no embedder call. |
| Does not | Run BGE-M3. Send chunks through `multimodal_legacy`. |

## 7j — Live translation

`PLAN.md` already places this in Phase 7. It stays here as its own small PR so the two docs match. It is not part of 7a.

| | |
|---|---|
| Files | `rooms/services.py` (replace the 501 `translate_to` path), per-reader cache on the message read model |
| Migrations | Only if the cache needs a column; otherwise none. |
| Endpoints | Existing `GET …/messages?translate_to=`. Flag off keeps today's 501. |
| Permission keys | `chat.use`, same as reading the room. Outsider and non-member stay 404/403 as they are now. |
| Flags | `live_translation` default off → 501. Flag on without `direct` configured → 501, and no network. |
| Behavior | Short text through `direct` only. Room messages are other members' content, and `multimodal_legacy` is plain HTTP, unauthenticated, in another account, and caches replies across users. Writes `UsageEvent` (`operation=translate`) and `AITrace`. The stored message body stays the original. The translation is per reader. A test asserts flag-on without `direct` stays 501 and does not call the legacy adapter. |
| Does not | Translate org documents. Call `multimodal_legacy`. |

## 7k — BYOK

Last. Decision 20, Decision 30, E20, Q13. Flag `byok` default off → 501 for everyone.

Two kinds of key:

| Kind | Who can create | Who can see `last4` or use it |
|---|---|---|
| Org key | owner, admin (`credential.manage`) | owner and admin of that org. Members 403. Secret never returned. |
| Personal key | the member who owns it | **only that user**. Another member, and an owner or admin, get 404 on read and cannot use it. `last4` only. |

| | |
|---|---|
| Files | `integrations/models.py`, `integrations/crypto.py`, `integrations/v2_views.py` |
| Migrations | `integrations/0002_credential` |
| Endpoints | `GET/POST /api/v2/orgs/{org}/credentials`, `PATCH/DELETE /api/v2/orgs/{org}/credentials/{id}` |
| Validation | A new key is `pending` until a check runs. The check uses the `direct` client with a minimal call (list models), 20-second timeout, mocked in tests. States (Decision 20): `pending`, `active`, `rejected`, `indeterminate` (timeout or 5xx), `disabled`, `expired`. No silent fallback to the platform key. A failed check does not mark the key active. |
| Tests | Ciphertext at rest. Response has `last4` and no secret. Personal-key isolation as above. A `multimodal_legacy` call does not put the credential in the body or the logs. Platform budgets ignore these calls. Mocked validation covers active, rejected, and indeterminate. |
| Does not | Forward a key to the multimodal host. Call a live provider. Turn `direct` on in production. |

## Not in Phase 7

Room-AI actions, buddies, turning on `private_only` (Q25 stays a configurable default), the WER audio files (E32), LiveKit (E30), Redis, and any AWS change.

## Gates

| Gate | What it blocks |
|---|---|
| Q13 | Sending a credential or an org document to the multimodal host. 7a–7j must not. 7k keeps the negative test. |
| Platform provider key (infra) | Selecting `direct` in production. 7b tests use mocked HTTP. |
| Embedding host | Turning `memory_search` on. 7h and 7i still land with the flag off. |
| Q25 | The final `private_only` model list. 7b only needs the client to accept a configured base URL. |
| Q28 | Applying migrations on ECS. Local tests still run them. |
