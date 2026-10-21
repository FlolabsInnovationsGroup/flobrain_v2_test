# FloBrain V2: Open Questions

Status: living list, 2026-10-20. Phases 0–6 are on `v2/phase-0-foundation`. Phase 7 starts on `v2/phase-7-ai`.

Each question has: **why it matters**, the **safe default** used until someone answers (spec rule 9: pick the safest reversible option and continue), the **phase that is blocked** if it stays open, and an **owner** guess. Answer inline under `Answer:` with a date and name, then move the result into `DECISIONS.md`.

Questions 1 to 25 come from the master prompt (Section 14). Questions 26 onward were raised by Discovery.

Legend for "Blocks": the first phase that cannot finish without an answer. "None" means the default is good enough to ship.

---

## A. Needed before or during Phase 0

### Q11. Memory nodes owned by `system`
After the D2 fix, `/api/memory/graph/` returns only the caller's nodes. Every node created through `POST /api/memory/save/` without an `owner_id` in the body is owned by the string `system`, so these nodes disappear from every V1 user's memory page.
- Default: keep them in the database, visible only to `is_platform_admin` (Decision E12). No deletion, no reassignment.
- Needs: a production count (`SELECT owner_id, count(*) FROM memory_nodes GROUP BY owner_id`) and a choice: migrate to real owners (only if traceable), keep admin-only, or delete.
- Blocks: none. Owner: backend lead + product.
- Answer: **Decided** 2026-10-20. Keep `system`-owned nodes in the database, visible only to `is_platform_admin`, until a human later asks to delete them. No migration and no reassignment (Decision E12). The row count is not needed for rollout, because nothing is changed or deleted. Q11 does not block rollout. SQL access is still unavailable.

### Q12. Tier-3 archives encrypted with the zero `AES_MASTER_KEY`
`memory/tier_3.py` defaults `AES_MASTER_KEY` to 64 zero hex characters. Every successful `POST /api/memory/save/` writes an S3 object and sets `tier_level = 3`. If production ran with the default key, rotating it makes those archives undecryptable (retrieval silently returns `{}`).
- Needs: (a) is `AES_MASTER_KEY` set in the ECS task definition? (b) `SELECT count(*) FROM memory_nodes WHERE tier_level = 3`; (c) does bucket `flobrain-cold-vault` (or `S3_VAULT_BUCKET`) contain `archive/` objects?
- Default: Phase 0 ships the startup check behind `ALLOW_INSECURE_AES_MASTER_KEY` (Decision E21) and changes no key.
- Blocks: none. Owner: whoever has AWS access.
- Answer: **Decided** 2026-10-20 (Decision E21). S3 holds no tier-3 archives: `flolabs-dev-uploads` has no `archive/` objects, and `flobrain-cold-vault` does not exist. The save path was read. `put_object` raises when the write fails. `migrate_node` sets `tier_level = 3` and `vault_uri` only after that call returns a URI. A failed write leaves the Postgres row at tier 1 or 2, with plaintext metadata, and no ciphertext that needs the zero key. The garbage-collection task sets tier 3 only when migrate returns true. The code writes to `S3_VAULT_BUCKET` (default `flobrain-cold-vault`), not to `flolabs-dev-uploads`. At the first V2 deploy, production gets a new random 64-hex `AES_MASTER_KEY`. `ALLOW_INSECURE_AES_MASTER_KEY` stays only as an emergency switch. This branch does not set the key.

### Q10. Org model for FloLabs
One organization "FloLabs" with ventures as teams/projects, or one organization per venture?
- Default: one org, ventures as projects (and teams where a venture has its own people). Every table is org-scoped either way, so splitting later is a data migration, not a schema change.
- Blocks: Phase 0 seed command content and Phase 1 data import. Owner: FloLabs leadership.
- Answer: 2026-10-20, default accepted (one org, ventures as projects/teams).

### Q26. Embedding model for memory (new)
Decision E16 picks the Postgres + Chroma path. That path needs an embedding vector per chunk, and today nothing in the backend produces one (`POST /api/memory/save/` expects the caller to send `embedding`; `hybrid_search` callers pass an all-zero 1536-length vector).
- Options: the multimodal service exposes `/embed`; a small self-hosted model on the API container or a worker; a provider API (OpenAI `text-embedding-3-small` is 1536-dim, which matches the zero vector the code assumes).
- Default: none chosen; Phase 7 cannot ship retrieval without it. Sovereign mode (Decision 50) needs a self-hosted option eventually.
- Blocks: none for the model choice. Memory search stays behind its flag until hosting is approved (INFRA_CHANGES.md).
- Answer: 2026-10-20. Self-hosted multilingual embeddings behind an `Embedder` interface (Decision E31). First choice **BGE-M3**, fallback **multilingual-e5**. The model can change without touching memory code. Every vector stores the model name and its dimension. The main account has no GPU today, so where the model runs is an infra decision, not a code decision.

### Q27. Staging environment (new)
Decision 45 makes staging + CI/CD part of Phase 0, but no staging stack, CloudFormation template or ECS task definition exists in this repository (see AUDIT.md section 5). The production stacks (`flolabs-dev-networking`, `flolabs-dev-application`) are named "dev" but serve `api.flobrain.ai`.
- Needs: where the CloudFormation templates live (another repo? console only?), who can create a staging stack, and whether staging gets its own RDS.
- Default: Phase 0 writes the pipeline files and `INFRA_CHANGES.md`, with deploy jobs disabled.
- Blocks: Phase 0 Definition of Done item "merges deploy to staging". Owner: DevOps.
- Answer: 2026-10-20, read-only audit. There is no staging stack. This branch stays undeployed, and every V2 feature stays behind a flag that defaults off.

### Q28. How migrations run on ECS today (new)
The Dockerfile `CMD` is `python manage.py runserver 0.0.0.0:8000` with no `migrate`. Only `docker-compose.yml` runs `migrate`. The repo does not show how production migrations are applied (one-off ECS task? manual `exec`?). Phase 0 adds the first V2 migrations to the `users` table.
- Default: document the current manual process once known; propose a one-off ECS migration task in `INFRA_CHANGES.md`.
- Blocks: none. Owner: DevOps.
- Answer: **Decided** 2026-10-20 (Decision E33). From now on, migrations run as the one-off ECS task in `INFRA_CHANGES.md`. How past migrations were applied is history and is asked of the team separately. It does not block the plan. The Dockerfile is not changed here.

### Q29. Production app server (new)
Production runs Django's development server (`runserver`) as the container command. It is single-process, not hardened, and not meant for production.
- Default: propose gunicorn in `INFRA_CHANGES.md` (Decision E26); do not change the image in a phase PR.
- Blocks: none for this branch. Owner: DevOps.
- Answer: **Decided** in principle 2026-10-20 (Decision E26). Switch to gunicorn with the first V2 deploy, through staging, as an infra change. Production today is still `runserver` because the task definition sets no command. Not applied from this branch.

### Q30. Is the deployed API in sync with `main`? (new)
`docs/FIX_LOGIN_AND_CHAT.md` says production lagged the repo, and the model registry is in the repo but not in the deployed schema. V2 compatibility is measured against what V1 clients actually call.
- Needs: the git SHA / image tag running on ECS, and whether production has `model_registry` migration `0001` applied.
- Default: treat `main` as the V1 contract.
- Blocks: none. Owner: DevOps.
- Answer: 2026-10-20, read-only audit. The running image is `flobrain-backend:latest`, a mutable tag last pushed **2026-08-19** (task definition `flolabs-dev-django:5`). It is not this branch. Whether `model_registry` `0001` is applied is still unknown (no SQL access, Q11).

### Q31. `SECRET_KEY` strength in production (new)
JWTs are HS256 signed with `SECRET_KEY`. The local key is 21 bytes and PyJWT warns below 32. V2 adds password-reset tokens and more privileged sessions on the same key.
- Default: Phase 0 adds a non-DEBUG startup warning (not a hard failure) when `SECRET_KEY` is shorter than 32 bytes or uses the `django-insecure` prefix. Rotating it logs every user out.
- Blocks: none. Owner: DevOps.
- Answer: **Decided** 2026-10-20 (Decision E34). The production `SECRET_KEY` is 66 characters, above the 32-byte HS256 floor, so there is no strength failure. The local key is still short and still warns. Rotation stays the `JWT_SIGNING_KEY` proposal in `TECH_DEBT.md` (not implemented). The key value is not recorded here.

---

## B. Multimodal service and AI

### Q1. Multimodal `/process` contract
The multimodal service is not in this repository (AUDIT.md section 4). Today Django sends only `multipart/form-data` with one field, `text_input`, and reads `result`, `model`, `file_type`, `total_tokens`. Questions for the multimodal team:
1. Which fields does `/process` accept? Specifically: `model`, image (file or base64 or URL?), document, audio, role-structured messages (JSON `messages[]`), a credential reference for BYOK.
2. Does it return `prompt_tokens` / `completion_tokens` (or input/output tokens), and `provider`?
3. What error body and HTTP codes does it return (the spec wants `CREDENTIAL_REJECTED`, `RATE_LIMITED`, ... mapped 1:1)?
4. How is `MULTIMODAL_API_KEY` checked (Bearer header as Django sends today)? Is it required in production?
5. Is there a credential validation endpoint (Notion: 20 s limit), and what does it return?
6. Is there an embeddings endpoint (see Q26) and a transcription endpoint (Q14)?
7. Who owns BYOK key storage long term (Notion lists unresolved decisions B1 to B7)?
- Default: Phase 0 forwards `model` as an extra multipart field named `model`. The service ignores that field. Chosen safe default for the provider layer: `AI_PROVIDER_BACKEND=multimodal_legacy` in production (Decision E29). The "Echoing input" HTTP 200 body is a provider error for V2, never an assistant reply and never memory. V1 keeps today's response shape.
- Blocks: none. The remaining asks are a proposal in `MULTIMODAL_CONTRACT_PROPOSAL.md`, not an open question.
- Answer: 2026-10-20, closed from `FlolabsInnovationsGroup/multi-modal-perception` `main` at `1d875b8`. The deployed EC2 host can differ from that commit.

  - Endpoints: `POST /process` and `POST /openAI` (identical logic), `GET /health`.
  - Input: multipart form. Only `text_input` (optional string) and `audio_file` (optional file). No `model`, image, document, `messages[]`, or credential field. Extra fields, including `model`, are ignored.
  - The service sends one user message plus a fixed system prompt ("fast, concise multimodal perception assistant ... short, actionable analysis"). It does not send conversation history unless the caller puts it inside `text_input`.
  - What V1 Django sends (`brain/views.py` `_build_llm_messages`, `brain/llm/multimodal_adapter.py`): a system line `You are FloBrain, a helpful AI assistant.` plus every user and assistant `text` in that chat, oldest first, flattened into one `text_input` string (`System: ...`, `User: ...`, `Assistant: ...`, separated by blank lines). Images stored on the user message are not included. Audio is not sent. If the client passed `model`, Django adds a `model` form field, which this service ignores. If `MULTIMODAL_API_KEY` is set, Django sends `Authorization: Bearer`; the service never checks it.
  - Model: `OPENAI_MODEL`, default `gpt-4o-mini`. `max_tokens=256`, `temperature=0.4`. Audio is transcribed with `gpt-4o-mini-transcribe` and then answered. The transcript is not returned.
  - Output: `result`, `model`, `file_type` only. `total_tokens` is computed and not returned, so Django cannot fill token fields from this service. V1 currently stores `0` when the field is absent.
  - Errors: 422 when both inputs are empty. 500 with a text `detail` when the service is misconfigured or crashes. When the OpenAI call fails: HTTP 200 and `Perception system temporarily unavailable. Echoing input: <the user's text>`. No error codes.
  - Auth: none. No credential validation, embeddings, or transcription endpoint. BYOK is not supported: one platform OpenAI key.
  - In-memory response cache keyed by the lowercased message. Shared by all users, never expires, no size limit. The same text returns the same cached answer for everyone, and memory grows until restart.

### Q13. HTTPS for the multimodal service
Default `MULTIMODAL_SERVICE_URL` is plain `http://35.153.90.219:8000`. The spec forbids sending any credential reference unless the URL is `https://` and `MULTIMODAL_API_KEY` is set.
- Default: BYOK forwarding is hard-disabled in code until both conditions hold. Production provider default is `multimodal_legacy` (Decision E29), not `direct`.
- Blocks: Phase 7 BYOK. Owner: DevOps + multimodal team.
- Answer: 2026-10-20, read-only audit. The service is an EC2 `t3.small` (no GPU) named `multi-modal-perception` in a separate AWS account, us-east-1, Elastic IP, the URL already in this repo. Plain HTTP, port 8000 open to the internet, no auth, no load balancer, no TLS, no logs. It proxies to OpenAI `gpt-4o-mini` (`MAX_TOKENS=256`). On error it returns HTTP 200 and `Perception system temporarily unavailable. Echoing input...`. A us-east-2 ECS move is unfinished and runs nothing. HTTPS is not in place, so BYOK stays disabled.

### Q14. Transcription route
Multimodal service (`gpt-4o-mini-transcribe`) or the team's own ASR (MiniCPM-o pipeline on JarvisLabs)? Arabic accuracy should decide.
- Blocks: none for the route. A provider is chosen by the interface, then compared with the benchmark set.
- Answer: 2026-10-20, closed. Transcription goes through the `ModelProvider` interface from the AWS findings (Decision E29 / E32), not a hard-wired ASR. Keep a small word-error-rate benchmark set in the repo, Arabic and English, so providers can be compared later. Do not add that set in this docs pass.

### Q25. Approved open models for `private_only`
Which self-hosted models cover chat, embeddings, transcription and translation, and on which GPUs?
- Blocks: none while the list stays configurable. Sovereign mode still needs the confirmed list before `private_only` is turned on. Owner: AI team.
- Answer: **Default (confirm: AI team).** Not final, and not hard-coded. Self-hosted on JarvisLabs GPUs behind `ModelProvider`, served with vLLM or Ollama. Chat: the best open model from the team's own eval (Qwen family already tested). Vision: MiniCPM-V (already being benchmarked on JarvisLabs). ASR: MiniCPM-o or Whisper large-v3, chosen by the Arabic/English WER set (E32). Embeddings: BGE-M3 (E31). Translation: the chat model first. The final list comes from Pulse evals (Phase 13), not from this file.

### Q32. V1 chat image handling (new)
V1 stores `image` on the user message (base64 or URL text) but never sends it to the model. When Phase 7 forwards images, should V1 `/api/brain/chats/<id>/send/` also start forwarding them (a behaviour change for V1), or only V2 threads?
- Default: V2 only; V1 unchanged.
- Blocks: none. Owner: product.
- Answer: 2026-10-20, default accepted.

---

## C. Product and permissions

### Q3. Impact score formula and weekly targets
Who defines them? A contribution-scoring proposal exists as a PDF, not in the specs.
- Default: "Not configured" slot (Decision 17).
- Blocks: none. Owner: FloLabs leadership.
- Answer: **Decided** 2026-10-20. Stays "Not configured" until leadership approves a formula (Decision 17). Candidate inputs, not code: completed tasks, confirmed shared contributions, required-meeting attendance, deadline reliability, team-lead confirmation (Contribution-Scoring MVP proposal). It stays separate from commissions. No formula until approved.

### Q4. Time entries of others
Should team leads approve or edit members' time entries, or only view them?
- Default: view only (matrix: admin V, lead V(T)); `approved_by/approved_at` columns exist but no endpoint writes them.
- Blocks: none. Owner: ops.
- Answer: 2026-10-20, default accepted (view only).

### Q5. Commission & Leads
Confirm data owner (finance/ops) and where the 35% commission rule applies.
- Blocks: none while the rate stays configurable. Phase 12 still waits for finance to confirm where 35% applies before that number is used. Owner: finance/ops.
- Answer: **Default (confirm: finance/ops).** Not final, and the 35% figure is not hard-coded. Members submit leads. A finance/ops person with `commissions.manage` reviews leads and records, approves, and marks commissions paid. The rate is set per project or product. Payouts are manual. FloBrain never stores bank or card details. The feature is off per user by default (Decision 18).

### Q6. Masterclass assignment
Which Notion property links a masterclass to a member?
- Blocks: none while the property name stays configurable. Owner: ops.
- Answer: **Default (confirm: ops).** Read the masterclass list from the Notion masterclass database through the Notion plugin. Filter by a people or team property if ops names one; otherwise show the full list ordered by title. Store no copy beyond the title and the link. The property name is config, not a constant.

### Q8. 1:1 notes
Should the "1:1 Notes" quick action from the prototype be in V2?
- Default: not built; mentor notes (Phase 11) cover the mentor/mentee case.
- Blocks: none. Owner: product.
- Answer: 2026-10-20, default accepted (not in V2).

### Q33. Who can see the org member directory email/phone? (new)
The matrix gives members "V (name, avatar, teams, presence only)" but the Phase 1 profile lists contact fields (Discord, email, LinkedIn, optional phone). Can a member see another member's email and phone?
- Default: members see name, avatar, teams, presence, Discord and LinkedIn; email and phone only for leads of a shared team, admins and owner.
- Blocks: Phase 1 serializer. Owner: product.
- Answer: 2026-10-20, default accepted.

### Q34. V1 personal users who are also company members (new)
A FloLabs intern may already have a V1 personal account with the same email. Is the V2 membership attached to that existing `users` row (keeping their V1 chats and memory), or is a new account required?
- Default: attach to the existing row (email is unique in `users`); their V1 data stays private to them and is never indexed into org memory.
- Blocks: Phase 1 register-member flow. Owner: product.
- Answer: 2026-10-20, default accepted (attach to the existing row).

---

## D. Infrastructure

### Q7. Redis (ElastiCache)
Approve Redis for realtime (Channels), shared rate limits, and the job queue?
- Default: polling fallback, per-process rate limits, synchronous jobs in dev only. No Redis until a human approves an infra change.
- Blocks: Phase 4 realtime (not Phase 4 itself, which ships with polling). Owner: DevOps.
- Answer: 2026-10-20, closed for the queue (Q17, PostgreSQL only). ElastiCache is not in the account. Realtime stays on polling. Redis/Channels is an unapproved proposal in `INFRA_CHANGES.md`, not a job broker.

### Q17. Job queue
Celery + Redis (ElastiCache) or AWS SQS?
- Default: PostgreSQL-backed queue. Celery + Redis stays a proposal, not the queue.
- Blocks: none for the broker choice. Workers still have to be built, on Postgres.
- Answer: 2026-10-20, closed. PostgreSQL-backed queue only (Decision E17). Redis and SQS are not in the account and are not the queue. Redis/Channels stays an unapproved proposal in `INFRA_CHANGES.md` for realtime, not for jobs.

### Q9. Refresh token in an httpOnly cookie
Now or after V2?
- Default: after V2 (Decision 26); recorded in TECH_DEBT.
- Blocks: none. Owner: frontend + security.
- Answer: 2026-10-20, default accepted (after V2).

### Q38. V1 dashboard error-logs key regression (new, from PR #250)
PR #250 renamed the `/api/dashboard/error-logs/` response key from `"error-logs"` to `"error_logs"`. The V1 frontend on `main` still reads `"error-logs"` (`flobrain-website/src/lib/api.ts:320`, `src/app/dashboard/components/workflow-engine/index.tsx:39`), so the dashboard alert list is always empty. No error is raised.
- Options: (a) backend returns both keys for a deprecation period; (b) frontend reads `error_logs`; (c) revert the key.
- Default: none applied. PR 0b is the natural place for (a) if you want it.
- Blocks: none for V2. Owner: whoever owns PR #250.
- Answer: 2026-10-20, option (a): PR 0b makes the backend return both `"error-logs"` and `"error_logs"` for a deprecation period.

### Q39. Health endpoint latency without MongoDB (new, from PR #250)
`/api/dashboard/health/` now pings MongoDB through `memory/mongo_client.py`, which creates `MongoClient` with no timeout options. If no MongoDB is reachable (Q36 suggests production may have none), each health request waits for pymongo's default server-selection timeout (30 s) before reporting `degraded`. The ALB checks `/`, not this endpoint, so this does not affect deploys, but the V1 dashboard will hang.
- Default: none applied; a short `serverSelectionTimeoutMS` in `mongo_client.py` would fix it.
- Blocks: none.
- Answer: **Decided** 2026-10-20. Applied: `memory/mongo_client.py` sets `serverSelectionTimeoutMS` and `connectTimeoutMS` from `MONGO_TIMEOUT_MS` (default 2000). `GET /api/dashboard/health/` still returns the same shape and reports `degraded` when Mongo is missing, without waiting 30 seconds.

### Q35. Chroma storage location in ECS (new)
`memory/tier_2.py` opens a persistent Chroma client at the hardcoded path `/app/vector_db` at import time. On ECS Fargate that path is the container's ephemeral disk, so vectors are lost on every deploy and are not shared between tasks.
- Options: EFS volume, Chroma server as its own service, or another vector store (pgvector on the existing RDS needs no new service).
- Default: make the path a setting in Phase 7; choose storage before Phase 7 ships.
- Proposed 2026-10-20: pgvector on the existing RDS (DECISIONS.md E16a).
- Blocks: none for the choice. Phase 7 still has to ship the flag-gated migration.
- Answer: 2026-10-20, closed. **pgvector** on the existing RDS (PostgreSQL 15.17), not Chroma, for any shared or production store (Decision E16a). The store sits behind an interface so Chroma can still be used for **local dev only**. Without the extension, memory search shows "Not configured". `db.t3.micro` (1 GB): keep HNSW parameters conservative (`TECH_DEBT.md`).

### Q36. MongoDB in production (new)
`docker-compose.yml` runs MongoDB locally, but the repo shows no production MongoDB. The only HTTP path that touches Mongo is `PATCH /api/memory/nodes/<id>/` (event log), which returns 500 after saving if Mongo is unreachable. Is there a production MongoDB, and does V2 still need it?
- Default: V2 does not add Mongo dependencies (audit events go to Postgres `audit_events`).
- Blocks: none. Owner: backend lead.
- Answer: 2026-10-20, default accepted. The same-day audit found no DocumentDB and no MongoDB in the account. PR #250 still makes `/api/dashboard/health/` and `/api/dashboard/error-logs/` depend on Mongo; see Q39. V2 does not add Mongo.

---

## E. Meetings, content, learning

### Q2. Voice/video provider
Zoom SDK, LiveKit, Daily, or another? Where do recordings come from (Zoom cloud, the Strapi meeting system demoed by ops, S3)?
- Blocks: none for the provider. Phase 5 still waits on the hosting choice in `INFRA_CHANGES.md` before `voice_video` is turned on.
- Answer: 2026-10-20, closed. **LiveKit** for Phase 5, behind a provider interface and the `voice_video` flag, which stays **default off** (Decision E30). Self-hosted LiveKit versus LiveKit Cloud is an infra decision, not a code decision. Recordings come from that LiveKit deployment once the hosting choice is made.

### Q15. Existing AI video editor code
Where does it live, and can its pipeline be called as a library or service from the GPU worker?
- Blocks: none while the call stays a worker API. Phase 9 still needs the repo link. Owner: AI team.
- Answer: **Default (confirm: AI team, repo location).** The existing editor (transcript-based cleanup and shorts, Claude Sonnet as the editing brain) runs as its own worker service on JarvisLabs. Content Studio calls it through the worker API with a `WorkerToken`. FloBrain never imports its code. Add the repo link when the AI team gives it. The URL is config.

### Q16. Social developer apps
Which social accounts are connected first, and who owns the developer apps (YouTube, LinkedIn, TikTok, Instagram/Facebook, X) needed for OAuth and app review?
- Blocks: none while the order and the private-until-audit rule stay configurable. Owner: marketing + engineering.
- Answer: **Default (confirm: marketing + engineering).** Not hard-coded. Developer apps are registered under FloLabs company accounts, not personal ones. Engineering owns the app credentials (stored encrypted, E20). Marketing owns the social accounts. Order: YouTube and LinkedIn first, then TikTok, Instagram and Facebook, then X. Start app reviews early. Content from unaudited TikTok apps is private-only, and YouTube uploads from unverified API projects stay private until the project passes an audit. Show "will publish as private until approved" instead of failing silently. X API posting is paid per use and is shown as a cost line.

### Q18. TTS provider
Which provider for script-to-video voiceovers, and which voices/languages are approved?
- Blocks: none while the provider stays behind an interface. Owner: content team.
- Answer: **Default (confirm: content team).** A TTS provider interface. First cloud provider with good Arabic (Egyptian and MSA) and English voices; a self-hosted model later for `private_only`. Voice cloning of a real person only with recorded consent (Decision 37). The provider name is config.

### Q19. Certificate signing
Who holds the Ed25519 signing key, and what text/branding do certificates carry?
- Blocks: none while wording stays config. Owner: leadership.
- Answer: **Default (confirm: leadership).** The platform holds the Ed25519 signing key as a secret (never in the repo), with a key version so it can rotate. Issuer is "FloLabs Innovations Group". The certificate shows name, program, dates, verified hours by category, and a QR code to the public verify page. Wording and branding come from leadership and the design system. Do not hard-code the wording.

### Q23. Meeting bot
Build our own bot per platform or use a meeting-bot API vendor? Platform terms (Zoom, Meet, Teams) must allow it.
- Blocks: none while the vendor stays behind the Phase 15 interface. Owner: product + legal.
- Answer: **Default (confirm: product + legal).** Use a meeting-bot vendor first (for example Recall.ai) behind the Phase 15 interface. Build our own only if cost or privacy requires it. The bot always announces itself. Recording consent follows Decision 37. The vendor name is config.

---

## F. Platform and commercial

### Q20. Retention defaults
How long to keep chat messages, recordings, transcripts and time entries?
- Default: keep everything until Phase 16 retention policies exist.
- Blocks: none until Phase 16. Nothing is deleted automatically before then. Owner: legal/ops.
- Answer: **Default (confirm: legal/ops).** All of these are configurable per org, not constants. Chat, docs, tasks, and time entries: kept while the org is active. Recordings: 90 days, then deleted unless pinned. Transcripts and summaries: 1 year. AI traces: prompt/response content 90 days, metadata 1 year. Audit events: at least 1 year. Deleting a source deletes its vectors. Until Phase 16 nothing is deleted automatically.

### Q21. Target markets for Phase 17
Which first external customers (bootcamps, universities, SMBs, MENA enterprises) and which identity providers and data regions do they need?
- Blocks: none while markets and IdPs stay config. Owner: leadership.
- Answer: **Default (confirm: leadership).** Bootcamps/universities and MENA SMBs first. SSO with Google Workspace and Microsoft Entra ID first. Data region is chosen per customer. Sovereign mode is for customers who need it. No market list is hard-coded.

### Q22. Pricing
Seat price, usage pass-through, and which features belong to which plan?
- Blocks: none for the structure. Numbers wait for leadership. Owner: leadership.
- Answer: **Default (confirm: leadership).** Structure only, no numbers. Per-seat plans plus model usage shown at cost, BYOK with zero markup, no opaque credits (Decision 49). Prices are config.

### Q24. Default MCP allowlist
Which external agents and MCP servers should be on the default allowlist?
- Blocks: none. The list starts empty. Owner: owner role (FloLabs).
- Answer: **Default (confirm: owner).** Empty by default. First candidates, read-only tools only: Notion, GitHub, Google Drive. Every server is security-scanned before it is added. Tool-list changes need owner re-approval (Decision 48). The candidate names are not an allowlist in code.

### Q37. Existing billing tables (new)
`customer_billing`, `payment_history`, `group_billing`, `group_payment_history` exist with no endpoints. Phase 17 says reuse them only if they fit. Are any rows in production (from the V1 Stripe flow on the frontend)?
- Default: leave untouched; Phase 17 decides.
- Blocks: none while the tables stay untouched. Owner: backend lead.
- Answer: **Default (confirm: backend lead).** Leave `customer_billing`, `payment_history`, `group_billing`, and `group_payment_history` untouched. Phase 17 builds new billing tables and reuses the old ones only if a count proves they hold data worth keeping. Do not drop or rewrite them in the meantime.

---

## Waiting for a person

These stay open. Use the default, and keep it configurable. Do not hard-code it.

| Question | Owner | What they must confirm |
|---|---|---|
| Q37 billing tables | backend lead | Leave the old billing tables untouched unless a count shows rows worth keeping |
| Q25 `private_only` models | AI team | The self-hosted list (vLLM or Ollama on JarvisLabs). Final names come from Pulse evals |
| Q15 AI video editor | AI team | The repo location. Content Studio calls a worker API and does not import the editor |
| Q18 TTS | content team | The first cloud provider for Arabic (Egyptian and MSA) and English |
| Q16 social publishing | marketing + engineering | Company-owned apps, YouTube and LinkedIn first, private-until-audit, X as a cost line |
| Q23 meeting bot | product + legal | A vendor first (for example Recall.ai), the bot announces itself, Decision 37 consent |
| Q24 MCP allowlist | owner | Empty allowlist. Notion, GitHub, and Google Drive are candidates only, read-only, after a scan |
| Q5 commission and leads | finance/ops | `commissions.manage` reviews and pays. The rate is per project. 35% is not hard-coded |
| Q6 masterclass | ops | The Notion people or team property, or the full list ordered by title |
| Q19 certificates | leadership | Wording and branding. Issuer "FloLabs Innovations Group". The signing key stays a secret |
| Q20 retention | legal/ops | The periods below, all per org. Nothing is deleted automatically before Phase 16 |
| Q21 first markets | leadership | Bootcamps/universities and MENA SMBs, Google Workspace and Entra ID, region per customer |
| Q22 pricing | leadership | The numbers. The structure is per-seat plus at-cost usage, BYOK with zero markup |
