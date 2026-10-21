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
- `direct` AI calls (Phase 7) need a platform provider key in Secrets Manager before production can select that backend. The key is not a code change. Do not put it in the task definition as plain text, and do not send it to the current multimodal host.

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

Same image and the same database. No public port and no ALB. Until that process exists, job-backed features report "unavailable". Do not run the queue inside the gunicorn workers. Not applied from this branch.

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
| `CREDENTIALS_ENCRYPTION_KEY` | Phase 7 credentials (empty is valid until then) |
| `MULTIMODAL_API_KEY` | Not set on the ECS task. The multimodal service does not check it. Do not treat it as configured. |
| `SMTP_*` | password-reset mail |
| `HR_WEBHOOK_SECRET` | Phase 1 |
| Redis URL | Proposal only, for Channels. Not the job queue (E17). |

## LiveKit hosting (Q2)

Phase 5 will use LiveKit behind a provider interface. `voice_video` stays default off until a human picks one of these and applies it. Do not apply either from a phase PR.

- **LiveKit Cloud**, or
- **self-hosted LiveKit** (its own host; the main account has no GPU, and this choice is separate from the embedding host below).

Recordings come from that deployment. No join URL until the flag is on and the chosen host answers.

## Embedding model hosting (Q26)

The model is BGE-M3, with multilingual-e5 as fallback, behind an `Embedder` interface (E31). The main account has **no GPU** today. Choose a host (a GPU box outside this account, or another approved machine) before memory search is enabled. Until that host is approved, the memory-search flag stays off and the feature shows "Not configured". Do not run the model inside the current `db.t3.micro` API task.

## Redis / Channels (proposal only)

Not approved. The account has no ElastiCache. The job queue is PostgreSQL only (E17); do not add Redis or SQS as the broker. If a human later wants Django Channels, that is a separate proposal: ElastiCache in staging, realtime only, flag default off. Polling stays the Phase 4 path until then.

## Website

Vercel already deploys `flobrain-website`. Production builds now require `NEXT_PUBLIC_API_URL` (F8). Set it per environment; do not restore the `api.flobrain.ai` fallback.
