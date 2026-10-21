# FloBrain V2 runbook

Local operations only until infra is approved. Never run these against production from this branch.

## Before deploying this branch

Do not deploy `v2/phase-0-foundation` until these are set on the ECS task. The live task has 12 env names and `DEBUG=False`. Details and the test name are in `INFRA_CHANGES.md`.

These two break production if the branch is deployed as it is:

- `AES_MASTER_KEY` is not set. With `DEBUG=False`, check `flobrain.E001` stops a healthy boot. At the first V2 deploy, set a new random 64-hex key (Q12). `ALLOW_INSECURE_AES_MASTER_KEY` is an emergency switch only.
- `CORS_ALLOWED_ORIGINS` is not set. The allowlist is localhost only, so the site on flobrain.ai loses API access. Set the real origins (confirm them; likely `https://flobrain.ai,https://www.flobrain.ai`).

The process still starts when these are missing, with the effect in parentheses:

- `FRONTEND_BASE_URL` — reset and invite links use `http://localhost:3000`. SMTP is also unset, and the reset mail is sent with `fail_silently=True`, so it is dropped.
- `HR_WEBHOOK_SECRET` — `POST /api/v2/integrations/hr/applicants` returns 503.
- `DRF_NUM_PROXIES` — client IP stays the ALB address. Set `1` before trusting throttles or audit IPs.
- `CREDENTIALS_ENCRYPTION_KEY` — empty, which is valid until Phase 7 credentials exist.
- Feature flags are not env vars. `realtime` and `voice_video` default off (ticket 503, no join URL).
- `JOBS_EAGER` — `False` when `DEBUG` is false, so jobs do not run inside the request.
- `AWS_STORAGE_BUCKET_NAME` and `AWS_REGION` are set on the task and are not read by this branch's Django settings.
- `MULTIMODAL_API_KEY` — V1 calls go out with no Bearer token.
- `MONGO_HOST` — defaults to localhost (Q39). V2 does not add Mongo.
- `S3_VAULT_BUCKET` — code default `flobrain-cold-vault`, which does not exist. Do not turn on tier-3 writes.
- `SECRET_KEY` is set as plain text. The process starts. JWTs use it; rotating it logs everyone out.
- `ALLOWED_HOSTS` is `*`. Leave it until the target group checks `/healthz`.

## Local backend

```
cd flobrain-core/backend
# SQLite (this machine has no Postgres):
set DB_ENGINE=sqlite
set DEBUG=True
set ALLOW_INSECURE_AES_MASTER_KEY=1
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_v2_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Checks (same as `django-backend-ci.yml`):

```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
```

## Local website

```
cd flobrain-website
# no NEXT_PUBLIC_API_URL → http://127.0.0.1:8000
npm run dev
```

Open `/w/signin`. Production / CI production builds must set `NEXT_PUBLIC_API_URL`.

## Deploy (proposed, not enabled)

See `.github/workflows/backend-deploy.yml` (`if: false`). Intended path:

1. Build the backend image from `flobrain-core/backend/Dockerfile`.
2. Run the one-off migrate task (INFRA_CHANGES).
3. Deploy to **staging** ECS.
4. Smoke: `GET /healthz` 200, `GET /api/v2/me` 401 without a token.
5. Manual promotion to production (human approval). Never automatic.

## Rollback

- ECS: revert the service to the previous task definition.
- Website: Vercel revert the previous deployment.
- Do **not** reverse additive migrations that drop columns. Forward-fix or restore from RDS.

## Restore from RDS backup

1. Snapshot restore to a new instance (do not overwrite prod in place).
2. Point staging at the restored instance and verify `/healthz`.
3. Cut over only after a human check. Q11 (system memory nodes) and Q12 (AES key) must be known before any decrypt of tier-3 archives.

## Incidents

1. **Declare.** Whoever notices a customer-facing problem posts in the incident channel: what is broken, since when, who is affected. Name one incident lead.
2. **Contain first.** Prefer switches that need no deploy: turn the feature flag off (platform console, org flags), set the org to `private_only`, revoke a leaked API token or webhook secret, end a support session. Roll back the release if a deploy caused it (see Rollback).
3. **Status page.** For anything customers notice, record an incident in the org's incidents (`incidents.manage`); the public status export shows its title and state only.
4. **Data incidents.** If personal data may have reached the wrong person (a permission bug, a leaked export link), the lead tells the org owner and leadership the same day. Keep the audit rows; never delete them. Export links expire after 5 minutes and files after `EXPORT_RETENTION_DAYS`; delete the file early with `purge_exports` if needed.
5. **Close.** Write a short postmortem within five working days: timeline, cause, what stopped it, what changes so it doesn't repeat. Add the follow-ups to TECH_DEBT or the backlog.

## Privacy requests

- A person asks from **Privacy**: "Prepare a copy" (their own data, every org, a zip link valid 5 minutes, file kept `EXPORT_RETENTION_DAYS`) or "Request deletion".
- Admins decide deletion in **Retention and deletion**. Approving erases, in that org: room messages they wrote (and their search vectors), time descriptions and private AI conversations, and starts offboarding. Commission and audit records stay. Nobody decides their own request, and an owner must hand ownership over first.
- Retention runs daily (`apply_retention`) and deletes nothing until an owner sets days.
