# FloBrain V2 infrastructure changes

Proposal only. Nothing in this file is applied by a phase PR. Do not change AWS, ECS, RDS, or production from application code.

Q11 does not block rollout: `system` nodes stay in the database for platform admins only. Q28's future procedure is the one-off migration task. Q29 is gunicorn at the first V2 deploy, through staging, and is not applied from this branch.

## Before deploying this branch

Do not deploy `v2/phase-0-foundation` until the items below are set on the task definition. The live task has 12 env names and `DEBUG=False`. Two of them stop or cut off production if this branch boots as-is. Confirmed by `organizations.tests.test_production_env`.

| Setting | On the task today | If this branch boots without it |
|---|---|---|
| `AES_MASTER_KEY` | Not set | `flobrain.E001` stops a non-DEBUG boot. At the first V2 deploy, set a new random 64-hex key (Q12). `ALLOW_INSECURE_AES_MASTER_KEY` is an emergency switch only, not the deploy plan. |
| `CORS_ALLOWED_ORIGINS` | Not set | Allowlist is `http://localhost:3000` and `http://127.0.0.1:3000` only. `https://flobrain.ai` cannot call the API. Set the real site origins (confirm them; a likely pair is `https://flobrain.ai,https://www.flobrain.ai`) before deploy. |
| `FRONTEND_BASE_URL` | Not set | Defaults to `http://localhost:3000`. Password-reset and invite links point at localhost. The process still starts. Mail uses `fail_silently=True`, and SMTP is also unset, so the message is dropped. |
| `HR_WEBHOOK_SECRET` | Not set | `POST /api/v2/integrations/hr/applicants` returns 503. The process still starts. |
| `DRF_NUM_PROXIES` | Not set | `NUM_PROXIES` is `None`. Behind the ALB, throttles and `AuditEvent.ip` see the proxy address, not the client. The process still starts. Set `1` before relying on those IPs. |
| `CREDENTIALS_ENCRYPTION_KEY` | Not set | Empty is valid. Phase 7 credential storage is not built. The process still starts. |
| Feature flags | Not env vars | `realtime` and `voice_video` default off. The realtime ticket is 503. Meetings store no join URL. |
| `JOBS_EAGER` | Not set | `False` when `DEBUG` is false. Job-backed features do not run inside the request. |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_REGION` | Set | This branch's Django settings do not read them. |
| `MULTIMODAL_API_KEY` | Not set | V1 calls the multimodal host with no Bearer token. The process still starts. |
| `MONGO_HOST` | Not set | Defaults to `localhost`. V1 health and error-logs can wait on Mongo (Q39). V2 does not add Mongo. |
| `S3_VAULT_BUCKET` | Not set | Code default remains `flobrain-cold-vault`. That bucket does not exist. Combined with the missing AES key, do not turn on tier-3 writes. |
| `SECRET_KEY` | Set, plain text | The process starts. JWTs are HS256 with this value. Rotating it logs everyone out. See the `JWT_SIGNING_KEY` proposal in `TECH_DEBT.md`. |
| `ALLOWED_HOSTS` | `*` | The process starts. Leave this until the target group uses `/healthz`. |

`test_starts_and_allows_production_origin_when_cors_is_set` boots with those 12 names (dummy values), `CORS_ALLOWED_ORIGINS=https://flobrain.ai,https://www.flobrain.ai`, and `ALLOW_INSECURE_AES_MASTER_KEY=1`, and expects `check` to pass with that origin allowed.

## Proposals for humans (do not apply from this branch)

- Move `SECRET_KEY` and `DB_PASS` to Secrets Manager, then rotate them. They are plain text on the task definition today.
- Multimodal: restrict port 8000 to the NAT address `98.89.195.180/32` now. Later put the service behind HTTPS and auth, or retire it once the `direct` adapter is approved.
- Pin `flobrain-backend` by digest or by a commit tag. `:latest` was last pushed 2026-08-19 and is mutable.
- RDS: consider Multi-AZ and a larger class before V2 production load. Enable log exports. The current class is `db.t3.micro` (1 GB, single-AZ).
- Migrations do **not** run on container start (Dockerfile `CMD` is `runserver` only; the task definition sets no command). When V2 migrations need to reach production, run one one-off task (`python manage.py migrate --noinput`) and start the web service only after it exits 0. Do not put `migrate` on every web task.
- Stand up staging before any V2 flag is turned on in production. Nothing in this branch is deployed.
- `direct` AI calls (Phase 7) need a platform provider key in Secrets Manager before production can select that backend. Also set `AI_DIRECT_BASE_URL` (HTTPS only), `AI_DIRECT_MODEL_ALLOWLIST`, `AI_DIRECT_PROVIDER` (the name used in `PriceTable`, for example `openai`) and the matching `PriceTable` rows (prices come from the provider's price list, entered by a human). The key is not a code change. Do not put it in the task definition as plain text, and do not send it to the current multimodal host.

## Staging stack

Stand up a **staging** copy of the current Django API (ECS Fargate + ALB + RDS Postgres) that is not production.

- Separate ECS service, target group, and RDS instance (or a named staging database on a shared instance if cost requires it; prefer a separate instance).
- `DEBUG=False`, `ALLOWED_HOSTS` starts as the staging hostname plus the task IP **until** the health check is switched (below).
- `CORS_ALLOWED_ORIGINS` = the staging website origin (no `CORS_ALLOW_ALL`).
- `DRF_NUM_PROXIES=1` (E19) so throttles and `AuditEvent.ip` use the client IP behind the ALB.
- `FRONTEND_BASE_URL` = staging website URL (password-reset links).
- `JOBS_EAGER=False`. The queue is PostgreSQL (E17). Job-backed features return `unavailable` until that worker exists. Redis is not the broker.

## Health check switch, then strict hosts

Today production uses `ALLOWED_HOSTS="*"` because the ALB health check sends the task IP as `Host` (AUDIT §5).

1. Point the ALB target-group health check at `GET /healthz` (implemented in PR 0b; skips host validation).
2. Confirm the service stays healthy.
3. Then set `ALLOWED_HOSTS` to the real API hostnames only (staging, then production).

Do not tighten `ALLOWED_HOSTS` before step 2.

## Container command (E26)

The image still runs Django's development server (`CMD python manage.py runserver 0.0.0.0:8000`). That is not changed in a phase PR.

Proposed production/staging command, applied in the ECS task definition with the first V2 deploy, through staging (Q29). Not applied from this branch:

```
gunicorn flobrain.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
```

Add `gunicorn` to `requirements.txt` in the same infra PR that changes the task definition. ASGI/uvicorn waits until Channels lands.

## Job worker process (E17)

Indexing and other job-backed features need a process that is not the web service. Add a separate ECS service, or a task that stays up, running:

```
python manage.py run_jobs
```

Same image and the same database. No public port and no ALB. Do not run the queue inside the gunicorn workers. Not applied from this branch.

- Set `JOBS_WORKER_ENABLED=True` on the web service **and** the worker only after the worker service exists. While it is `False` (the default), `enqueue` creates no row and job-backed features report "unavailable", so nothing piles up in the queue.
- The worker keeps polling (`JOBS_POLL_SECONDS`, default 2) and stops cleanly on SIGTERM after the current job, so ECS can stop or replace it.
- A row left in `running` by a crashed worker is put back in the queue after `JOBS_STALE_SECONDS` (default 900).
- One worker task is enough to start. More can run at once: PostgreSQL `SKIP LOCKED` keeps them from taking the same row.

## One-off migration task (Q28)

Migrations are not defined on ECS today (P2). Proposed default:

1. A one-off ECS task (same image, same env, `command: python manage.py migrate --noinput`).
2. The web service starts only after that task exits 0 (CodeDeploy / Step Functions / a workflow step).
3. Never run `migrate` inside every web task (race).

`seed_v2_demo` must never run in staging or production (`DEBUG=False` already refuses).

## New secrets (env / Secrets Manager)

Create these in staging first. Do not commit values.

| Name | Why |
|---|---|
| `SECRET_KEY` | already required |
| `AES_MASTER_KEY` | New random 64-hex key at the first V2 deploy (Q12). `ALLOW_INSECURE_AES_MASTER_KEY` is an emergency switch only |
| `CREDENTIALS_ENCRYPTION_KEY` | BYOK (7k). 64 random hex characters (`openssl rand -hex 32`), never all zeros. Empty keeps BYOK at 501. Losing it makes stored keys unreadable (users re-enter them). Keep `CREDENTIALS_KEY_VERSION=1` until rotation ships |
| `BYOK_ALLOWED_HOSTS` | Optional. Comma list of provider hosts customer keys may call. Default: OpenAI, OpenRouter, Groq, Together, Mistral, DeepSeek, Fireworks |
| `MULTIMODAL_API_KEY` | Not set on the ECS task. The multimodal service does not check it. Do not treat it as configured. |
| `SMTP_*` | password-reset mail |
| `HR_WEBHOOK_SECRET` | Phase 1 |
| Redis URL | Proposal only, for Channels. Not the job queue (E17). |
| `STRIPE_WEBHOOK_SECRET` | Phase 17b. Stripe endpoint signing secret (`whsec_…`). Empty → the webhook returns 501. `BILLING_ENFORCE_ENTITLEMENTS` stays off until plans are seeded |
| `AI_SELF_HOSTED_HOSTS` | Phase 17a. Comma list of model hosts that count as private for `private_only` orgs. Empty → `private_only` orgs get no AI |
| `PUBLIC_API_BASE_URL` | Already used by Phase 14. SSO (17c) registers `PUBLIC_API_BASE_URL/api/v2/sso/callback` as the IdP redirect URI; it must be the public https API origin |
| SSO / SCIM | Phase 17c/17d. No new env. Client secrets are stored encrypted with `CREDENTIALS_ENCRYPTION_KEY` (empty → SSO setup returns 501). Domain verification makes DNS TXT lookups from the API task (outbound UDP/TCP 53 to the VPC resolver). IdP discovery, JWKS and token calls use the SSRF-safe pinned client (https, public IPs only) |
| `EXPORT_MAX_PER_DAY`, `EXPORT_RETENTION_DAYS`, `EXPORT_MAX_MESSAGES` | Phase 17e. Optional (3, 7, 500000). Exports use the Content Studio bucket (`CONTENT_STORAGE=s3`, `CONTENT_S3_BUCKET`) under `exports/<org>/`; empty storage → 501. Needs `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on that prefix, and a daily `python manage.py purge_exports` (or an S3 lifecycle rule on `exports/` at 8 days) |
| `CERTIFICATE_SIGNING_KEY` | Phase 11. Ed25519 private key, 32 random bytes in base64 (`python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`), in Secrets Manager. To rotate, put the old public key (from `/api/public/certificates/public-key`) in `CERTIFICATE_PREVIOUS_PUBLIC_KEYS` (comma list) before switching the private key, or older certificates stop verifying |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Phase 10 Web Push. Generate once (`vapid --gen` from `py-vapid`), private key in Secrets Manager. Empty: push is off. Outbound HTTPS from the worker to the browser push services (FCM, Mozilla, Apple, Microsoft) |
| Privacy center (Phase 16) | No new env. Personal data downloads use the same bucket under `privacy/<user>/` (`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on that prefix) and `EXPORT_RETENTION_DAYS`. Retention needs a daily `python manage.py apply_retention`; it deletes nothing until an owner sets days |
| `AI_FORCE_PRIVATE_ONLY`, `AI_ALLOW_PLAINTEXT_HOSTS` | Phase 17f. Sovereign installs only. Leave both unset on FloBrain's hosted deploy |
| SAML (2026-10-21) | No new env. Needs `PUBLIC_API_BASE_URL` (the ACS is `/api/v2/sso/saml/acs`, the SP entity id and metadata `/api/v2/sso/saml/{org}/metadata`). New packages `signxml==5.1.0`, `lxml==6.1.3` |
| `STRIPE_SECRET_KEY` | 2026-10-21. Server-side Checkout and billing portal sessions (owners only). Empty: checkout answers 501 |
| `EXTERNAL_AGENT_ALLOWED_HOSTS` | Outside MCP agents. Upper bound of hosts an owner may allow; empty means none. Calls use the SSRF-safe pinned client |
| `PII_DETECTOR` | 2026-10-21. `regex` (basic, `platform_api/pii.py`) or a dotted class path. Empty: orgs can't turn on redaction (501). Demo mode defaults to `regex` |
| `TTS_PROVIDER` | Content Studio voiceover. Empty: 501. Waits for Q18 (`demo` exists for demo mode only) |
| `CONTENT_LOCAL_DIR` | Dev and demo only: local storage folder for `CONTENT_STORAGE=local` (signed, expiring URLs). Not for ECS (task disks are not shared) |
| `DOCS_FILE_STORAGE`, `DOCS_LOCAL_STORAGE_DIR`, `DOCS_MAX_UPLOAD_MB` | Doc attachments. Local storage only for now (S3 not built), so on ECS attachments answer 501 |
| `DEMO_TICKS`, `DEMO_TICK_SECONDS` | Demo only: the scheduled commands run inside the web process (default on, every 60 s). Never relevant with `DEMO_MODE` off |
| `tick_tasks` | Hourly scheduled command (task reminders). Added to the compose ticker and the Helm cronjobs |
| `NEXT_PUBLIC_STATUS_JSON_URL` | Website (Vercel). The hosted `status.json` from `export_status`; empty: the status page reads the API |

## Meetings stack (Q2 and Q23, decided 2026-10-21: self-hosted)

Calls, recording, transcription and the meeting assistant all run on our own servers (`deploy/meetings/`, `whisper-server/`, `meeting-bot/`). Nothing is applied from a PR; a human deploys it.

| Setting (API) | Value |
|---|---|
| `LIVEKIT_URL` | Browser address, `wss://calls.<domain>` (TLS in front of LiveKit 7880) |
| `LIVEKIT_API_URL` | Server-side address, e.g. `http://livekit:7880` |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | One key pair, the same in `livekit.yaml` and `egress.yaml` (Secrets Manager) |
| `ASR_BACKEND=http`, `ASR_BASE_URL`, `ASR_API_KEY` | The Whisper service; key optional |
| `MEETING_BOT_VENDOR=self_hosted`, `MEETING_BOT_MAX_MINUTES` | Turns on the assistant (120 minutes by default) |
| `MEETING_UPLOAD_MAX_MB` | Upload limit for recordings (500) |

Also: a `meeting_bot` worker token (`manage.py worker_token --issue meeting-bot-1 --kind meeting_bot`), Egress writing to the content bucket under `meetings/`, and the LiveKit webhook pointing at `https://<api>/api/v2/livekit/webhook`. Network: TCP 7881 and UDP 50000–50100 to users, TURN for strict firewalls, outbound internet for Egress and the bot.

## Embedding model hosting (Q26)

BGE-M3 runs on JarvisLabs (team decision 2026-10-20). FloBrain needs: `EMBEDDINGS_BACKEND=http`, `EMBEDDINGS_BASE_URL` (HTTPS, OpenAI-compatible `/v1/embeddings`), `EMBEDDINGS_MODEL`, `EMBEDDINGS_DIMENSION=1024`, and `EMBEDDINGS_API_KEY` if the endpoint requires one (Secrets Manager). The JarvisLabs endpoint should accept only the NAT IP `98.89.195.180` or require the key.

Phase 7i adds, all optional with defaults: `KNOWLEDGE_CHUNK_CHARS` (1500), `KNOWLEDGE_CHUNK_OVERLAP` (200), `KNOWLEDGE_ASK_TOP_K` (8), `KNOWLEDGE_CONTEXT_CHARS` (12000). To turn knowledge ask on for one org, in order: pgvector extension present (`knowledge/0001` creates it when RDS allows), embeddings env set, `direct` provider env set, job worker running (`JOBS_WORKER_ENABLED=True`), org flag `memory_search` on, then `manage.py index_knowledge --org <id>` once. Answers go only to the `direct` provider, never the multimodal host.


The model is BGE-M3, with multilingual-e5 as fallback, behind an `Embedder` interface (E31). The main account has **no GPU** today. Choose a host (a GPU box outside this account, or another approved machine) before memory search is enabled. Until that host is approved, the memory-search flag stays off and the feature shows "Not configured". Do not run the model inside the current `db.t3.micro` API task.

## Redis / Channels (proposal only)

Not approved. The account has no ElastiCache. The job queue is PostgreSQL only (E17); do not add Redis or SQS as the broker. If a human later wants Django Channels, that is a separate proposal: ElastiCache in staging, realtime only, flag default off. Polling stays the Phase 4 path until then.

## Website

Vercel already deploys `flobrain-website`. Production builds now require `NEXT_PUBLIC_API_URL` (F8). Set it per environment; do not restore the `api.flobrain.ai` fallback.
