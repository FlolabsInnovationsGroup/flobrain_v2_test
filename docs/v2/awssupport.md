# FloBrain AWS: how it runs today, and what V2 needs

**To:** Arsema, Lucas (AWS / DevOps)
**From:** FloBrain team
**Status:** Final for handoff (V2 code complete: Phases 0 to 17, self-hosted meetings, SAML, and the 2026-10-21 completion work, on a local branch, not deployed). Source: `docs/v2/awssupport.md`.
**Last update:** 2026-10-21

Nothing in this document has been applied to AWS. Everything came from read-only audits (Describe/List/Get only). The detailed engineering source is `docs/v2/INFRA_CHANGES.md`. This file is the human summary of it.

---

## 0. What each team needs to do (short version)

Each step is safe to do on its own. Until a step is done, the matching FloBrain feature says "not set up" and nothing else breaks.

**AWS / DevOps (Arsema, Lucas)**
1. Security items S1 to S6 (section 2), S1 and S3 first.
2. Staging environment (3.1), then the settings in 3.2 as secrets. The two red items block boot.
3. `/healthz` health check, then strict `ALLOWED_HOSTS` (3.3); gunicorn (3.4); migrations as a one-off task (3.5).
4. The worker service `run_jobs` (3.6) and the scheduled commands (3.11, nine of them now).
5. RDS upgrade and pgvector (3.7); private S3 bucket with the prefixes in 3.11.
6. Meetings stack (3.12): Redis, LiveKit with TLS, Egress, Whisper, the meeting bot.
7. Static hosting for the public status page (3.14).
8. Optional: a separate demo environment (3.15). Never `DEMO_MODE` on production.

**Multimodal team:** `multimodalsupport.md` (P0 security this week; meetings no longer need them).

**AI team (JarvisLabs):** the OpenAI-compatible endpoint for `AI_DIRECT_*`, the BGE-M3 embeddings endpoint, and the self-hosted model names for "private only" orgs (Q25), all over HTTPS, accepting only the NAT IP or an API key.

**Owners / product:** answers to the open questions in `OPEN_QUESTIONS.md` (the "Waiting for a person" table): billing plans and prices (Q22), the TTS provider (Q18), social apps (Q16), the MCP allowlist (Q24), legal terms for the meeting bot (Q23).

**Website (Vercel):** set `NEXT_PUBLIC_STATUS_JSON_URL` once the status file is hosted (3.14). Nothing else changes on Vercel.

---

## 1. How it runs today

```
Users ─► flobrain.ai (Next.js on Vercel)
       └► api.flobrain.ai ─► ALB (HTTPS, ACM cert) ─► ECS Fargate "flolabs-dev-django-service"
                                                        │  task def flolabs-dev-django:5
                                                        │  image flobrain-backend:latest (pushed 2026-08-19)
                                                        │  runs: python manage.py runserver (Django dev server)
                                                        ├─► RDS PostgreSQL 15.17 "flolabs-dev-postgres"
                                                        │   db.t3.micro, single-AZ, encrypted, private
                                                        ├─► S3 flolabs-dev-uploads (private, versioned)
                                                        └─► NAT 98.89.195.180 ─► http://35.153.90.219:8000
                                                              (multimodal EC2, second AWS account)
```

**Main account (FloBrain production, us-east-1):**
- CloudFormation stacks: `flolabs-dev-networking`, `flolabs-dev-application`, `flolabs-storage-iam`. There is no staging stack.
- 12 environment variables, all **plain text** in the task definition, including `SECRET_KEY` and `DB_PASS`. Nothing comes from Secrets Manager or SSM.
- `ALLOWED_HOSTS="*"`, because the ALB health check sends the task IP as `Host`. Do not tighten this before step 3.3 below.
- No Redis, SQS, MongoDB, EFS, Route 53 zones or EC2 instances.
- ECS Exec is disabled. There are no scheduled tasks, and no command is set on the task definition.

**Main account, us-east-2:**
- An unfinished plan to move the multimodal service to ECS: two empty clusters, an empty ECR repo `multi-modal-perception`, an empty log group, and an IAM role `GitHubActionsECSFargateRole` that was never used. Details in 2.1.

**Second account (multimodal):**
- EC2 `multi-modal-perception`, t3.small (no GPU), Elastic IP `35.153.90.219`. Port 8000 is open to `0.0.0.0/0`, with no authentication.
- A stopped EC2 `Flobrain-backend`.
- 5 IAM users. The audit session ran as **root**.

---

## 2. Security items (please handle first)

| # | Item | Why | Suggested fix | Who |
|---|---|---|---|---|
| S1 | `GitHubActionsECSFargateRole` (main account) trusts `repo:multi-modal-perception/autodeploy:ref:refs/heads/main`. The real repo is `FlolabsInnovationsGroup/multi-modal-perception`. Its ECS permissions are on `*`. | Harmless **today** only because the GitHub OIDC provider is not registered. If someone registers the provider to fix CI without fixing the trust, anyone who creates a GitHub account named `multi-modal-perception` could assume the role. They could then read FloBrain's task definition (plain-text secrets) and update the production service. | Fix the trust to the real repo with `StringEquals`, and scope the ECS permissions to the multimodal cluster and service only. Register the OIDC provider only after that. Or delete the role if the migration is abandoned. | Lucas (created around 2026-09-24?) |
| S2 | Multimodal EC2 port 8000 is open to the world, with no auth, and it holds the OpenAI key. | Anyone can use the OpenAI account. | Change the inbound rule to `98.89.195.180/32` (the FloBrain NAT IP). Set an OpenAI spend limit. Details in `multimodalsupport.md`. | Multimodal team, with your help on the security group |
| S3 | `SECRET_KEY` and `DB_PASS` are plain text in the task definition. | Anyone with `ecs:DescribeTaskDefinition` can read them. | Move them to Secrets Manager (task definition `secrets`), then rotate the DB password. Rotating `SECRET_KEY` logs every user out, so plan it. | Arsema |
| S4 | The second account is used as root. | Root has no limits and should not be used for daily work. | MFA on root. Use IAM users or roles for daily work. | Account owner |
| S5 | Dormant IAM users (for example `miki-admin`, never signed in). | Unused credentials are a risk. | Review and remove the unused ones. | Account owner |
| S6 | Stopped EC2 `Flobrain-backend` (second account). | Cost and confusion. | Snapshot if needed, then decide whether to keep it or terminate it. | Arsema |

---

## 3. What the V2 deploy needs (in order)

V2 is being built on local branches and is **not deployed**. Every V2 feature is behind a flag that defaults to off. When the code is ready, this is the order we propose.

### 3.1 Staging first

A staging copy of the API: a separate ECS service, target group and RDS instance (or a separate database if cost requires it), with `DEBUG=False`. Production only receives builds that passed staging.

### 3.2 Settings that must exist before V2 boots

Two of these break production if they are missing:

| Setting | Today | If missing when V2 boots | Value |
|---|---|---|---|
| `AES_MASTER_KEY` | not set | 🔴 Django refuses to start (check `flobrain.E001`) | A new random 64-hex key in Secrets Manager. No existing data depends on the old zero key (checked). |
| `CORS_ALLOWED_ORIGINS` | not set | 🔴 the website loses API access (only localhost allowed) | `https://flobrain.ai,https://www.flobrain.ai` (confirm the real domains) |
| `FRONTEND_BASE_URL` | not set | Password-reset and invite links point at localhost | `https://flobrain.ai` (or the staging site) |
| `SMTP_HOST/PORT/USER/PASS` | not set | Reset and invite emails are dropped | The mail provider |
| `DRF_NUM_PROXIES` | not set | Rate limits and audit logs see the ALB IP, not the user | `1` |
| `HR_WEBHOOK_SECRET` | not set | The HR intake webhook returns 503 | A random secret, shared with the n8n flow |
| `CREDENTIALS_ENCRYPTION_KEY` | not set | Customer API keys (BYOK) cannot be stored (feature shows "Not configured") | 64 random hex characters (`openssl rand -hex 32`) in Secrets Manager. Never all zeros. If it is lost, customers re-enter their keys |
| `MULTIMODAL_API_KEY` | not set | Calls to the multimodal service carry no key | The key the multimodal team issues (`multimodalsupport.md`, step 3) |
| `AI_DIRECT_BASE_URL`, `AI_DIRECT_API_KEY`, `AI_DIRECT_MODEL_ALLOWLIST`, `AI_DIRECT_DEFAULT_MODEL` | none | V2 AI features (knowledge ask, translation, room AI on `direct`) stay "Not configured" | Base URL over HTTPS (for example `https://api.openai.com`), the key in Secrets Manager, and the allowed model names. `AI_PROVIDER_BACKEND=direct` moves room AI off the multimodal host |
| `EMBEDDINGS_BACKEND=http`, `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_MODEL`, `EMBEDDINGS_DIMENSION=1024`, `EMBEDDINGS_API_KEY` | none | Memory search stays "Not configured" | The BGE-M3 endpoint on JarvisLabs (HTTPS) and its key |
| `PUBLIC_API_BASE_URL` | none | SSO and social-account sign-in send people back to `localhost` (both fail) | `https://api.flobrain.ai`. Customers register `https://api.flobrain.ai/api/v2/sso/callback` as the SSO redirect URI |
| `STRIPE_WEBHOOK_SECRET` | none | The Stripe webhook returns 501 (billing stays manual) | The endpoint signing secret from the Stripe dashboard, in Secrets Manager. Keep `BILLING_ENFORCE_ENTITLEMENTS` off until plans exist |
| `AI_SELF_HOSTED_HOSTS` | none | Orgs that choose "private only" get no AI at all | The hostname(s) of our self-hosted models (for example the JarvisLabs vLLM and BGE-M3 hosts). Not secret |
| `STRIPE_SECRET_KEY` | none | Owners can't start a Stripe checkout or open "Manage billing" (both answer "not set up") | The Stripe secret key, in Secrets Manager. Checkout sessions are created on the server only |
| `EXTERNAL_AGENT_ALLOWED_HOSTS` | none | No org can connect an outside AI agent (MCP). This is the upper bound; each owner then picks from it | Comma-separated hostnames, decided with the owners (Q24). Empty is a safe default |
| `PII_DETECTOR` | none | Orgs can't turn on "remove personal details before AI" (answers "not set up") | `regex` for the basic built-in detector, or a stronger detector class later. Not secret |
| `TTS_PROVIDER` | none | Content Studio voiceover answers "not set up" | Waits for the TTS decision (Q18) |
| `CONTENT_STORAGE=s3`, `CONTENT_S3_BUCKET`, `CONTENT_S3_REGION` | none | Content Studio uploads, renders, exports and privacy downloads answer "not set up" | The private bucket from 3.11 |
| `DEMO_MODE` | not set | Must stay **unset** on production and staging. It turns on the sample data, demo sign-in, the demo identity provider and the demo AI | Only in the separate demo environment (3.15) |

Document attachments (Docs tab) work only with local file storage today; S3 for them is not built yet, so on ECS they answer "not set up". This is in `TECH_DEBT.md`.

New Python packages in this build: `signxml` and `lxml` (SAML). They are in `requirements.txt`; a normal image rebuild installs them.

There is a test in the repo (`ProductionEnvBootTests`) that boots the app with exactly the production variable names. It proves the two red items are the only boot blockers.

### 3.3 Health check, then strict hosts

1. Point the ALB target-group health check (and the container health check) at `GET /healthz`. V2 serves it without host validation.
2. Confirm the service stays healthy.
3. Only then set `ALLOWED_HOSTS` to the real API hostnames. (Tightening it before step 2 broke production once already.)

### 3.4 App server

Run gunicorn instead of `runserver`:

```
gunicorn flobrain.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
```

Set it in the task definition `command`. Pick the worker count to match the task CPU and memory.

### 3.5 Migrations

Production does **not** run migrations on container start. Arsema confirmed (2026-10-21) that they are run by hand as a one-off ECS task (`aws ecs run-task` with a `migrate` command override); there is no migration step in the pipeline yet (planned). For V2, keep that pattern and add it to the pipeline:
- run one **one-off ECS task** (same image, same env, `python manage.py migrate --noinput`),
- start or update the web service only after it exits 0,
- never run `migrate` inside every web task.

### 3.6 Background worker

V2 uses a PostgreSQL-backed job queue (no Redis, no SQS). It needs **one more ECS service** from the same image, running:

```
python manage.py run_jobs
```

It has no public port and no ALB, and uses the same database and secrets. Until it exists, background features (indexing, transcription jobs) show "unavailable".

- After the worker service is running, set `JOBS_WORKER_ENABLED=True` on both services.
- The worker stops cleanly on SIGTERM, so normal ECS deploys are safe.
- One task is enough to start.

### 3.7 Database

- **pgvector:** V2 runs `CREATE EXTENSION IF NOT EXISTS vector` in a migration. PostgreSQL 15.17 on RDS supports it, and the master user can create it. Nothing else to install.
- **Before V2 load:** move from db.t3.micro (1 GB) to a larger class, consider Multi-AZ, and enable log exports (postgresql log). Vector indexes need memory.
- **Backups:** retention is 7 days today. Consider more before V2 data grows.

### 3.8 Images and CI

- Deploy by commit tag or digest, not `:latest`.
- The backend deploy workflow in the repo (`.github/workflows/backend-deploy.yml`) is disabled (`if: false`). When you set up GitHub OIDC for it, use the real repo in the trust policy (see S1) and scope permissions to the FloBrain service only.

### 3.9 External services V2 will call

| Service | What | Needs from you |
|---|---|---|
| Multimodal service | V1 chat today | Network path: SG allowlist on the NAT IP, or a private-network move (`multimodalsupport.md` P1-5) |
| AI provider (OpenAI or a self-hosted OpenAI-compatible server) | V2 AI features | Outbound HTTPS from the NAT (works today), and the key in Secrets Manager |
| Embeddings (BGE-M3 on JarvisLabs) | Memory search | The JarvisLabs endpoint should accept only the NAT IP `98.89.195.180` (or use an API key), over HTTPS |
| LiveKit (Cloud or self-hosted) | Voice and video (Phase 5) | Decision pending. Cloud needs only keys in Secrets Manager. Self-hosted needs its own host with UDP ports. |
| Social platforms (YouTube, LinkedIn, TikTok, Meta, X) | Content Studio publishing (Phase 9) | Nothing on AWS. App credentials go in Secrets Manager. |
| Customer identity providers (Google Workspace, Entra ID, Okta) | SSO (Phase 17c) | Outbound HTTPS from the NAT (works today). Domain verification makes DNS TXT lookups from the task through the VPC resolver (default VPC DNS is enough) |
| Customer webhook URLs | Outbound webhooks (Phase 14) | Outbound HTTPS from the NAT to public IPs only; the code refuses private and metadata addresses |
| Stripe | Billing webhook (Phase 17b) and checkout | Inbound: Stripe calls `POST /api/v2/billing/stripe/webhook` through the ALB. Outbound HTTPS to `api.stripe.com` for checkout. No new rule if the ALB already accepts public HTTPS |
| Customer SAML identity providers | SAML sign-in | Nothing outbound: the browser carries the signed answer to `https://api.flobrain.ai/api/v2/sso/saml/acs`. Needs `PUBLIC_API_BASE_URL` set correctly, because it is part of every org's SAML address |
| Notion | Masterclasses (learning) | Outbound HTTPS to `api.notion.com` from the NAT (works today). Each org pastes its own internal integration token; it is stored encrypted with `CREDENTIALS_ENCRYPTION_KEY` |
| Outside AI agents (MCP servers) | External agents | Outbound HTTPS from the NAT, only to hosts in `EXTERNAL_AGENT_ALLOWED_HOSTS`. Private and metadata addresses are refused in code |
| SMTP | Status page subscriptions, invites, resets | Same `SMTP_*` settings as 3.2 |

### 3.10 Rough monthly cost impact (to confirm with AWS Pricing Calculator)

- Staging environment (ECS + small RDS): about the same as the current production stack.
- Worker service: one more small Fargate task.
- Larger RDS class and Multi-AZ: the main cost increase.
- Secrets Manager: a small per-secret monthly charge.

### 3.11 Scheduled commands and S3 prefixes

All run from the same image and env as the API, as one-off ECS tasks (EventBridge Scheduler → ECS RunTask), never inside the web tasks:

| Command | Schedule | Why |
|---|---|---|
| `python manage.py tick_agents` | every minute | Scheduled AI agents (Phase 8) |
| `python manage.py tick_webhooks` | every minute | Webhook retries (Phase 14) |
| `python manage.py tick_content` | every minute | Content Studio queue and scheduled posts (Phase 9) |
| `python manage.py tick_pulse` | every 5 minutes | Pulse alert rules (Phase 13) |
| `python manage.py tick_automations` | every minute | Workflows, daily brief and nudges (growth round) |
| `python manage.py run_data_reports` | every hour | Data buddy sheet refresh and scheduled reports (growth round) |
| `python manage.py tick_tasks` | every hour | "Due tomorrow" and "overdue" task reminders. Safe to run twice |
| `python manage.py purge_exports` | daily | Deletes expired org memory exports (Phase 17e). An S3 lifecycle rule that expires `exports/` after 8 days is an acceptable replacement |
| `python manage.py apply_retention` | daily | Deletes data older than each org's retention policy, with its search vectors (Phase 16). Nothing is deleted until an owner sets a policy |

S3 (the private Content Studio bucket, `CONTENT_S3_BUCKET`): the task role needs `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` on `content/*`, `exports/*`, `privacy/*` (personal data downloads, Phase 16) and `meetings/*` (call recordings, 3.12). Downloads are 5-minute presigned links; the bucket stays private.

### 3.12 Meetings: calls, recording, transcription, assistant (decided 2026-10-21)

The owner decided meetings run on our own servers, with no outside vendor. Four services, all in `deploy/meetings/` (compose for reference). This is the AWS version:

| Service | AWS shape (proposal) | Notes |
|---|---|---|
| LiveKit server `livekit/livekit-server:v1.9.11` | ECS on **EC2** (not Fargate: it needs a UDP port range and host networking), 2 vCPU / 4 GB to start | Public: TCP 7880 behind TLS as `wss://calls.flobrain.ai` (NLB TLS listener or ALB), TCP 7881 and **UDP 50000–50100** through an NLB or an Elastic IP. TURN on 443 for users behind strict firewalls |
| LiveKit Egress `livekit/egress:v1.10.0` | ECS on EC2, needs `SYS_ADMIN`, 4 vCPU / 8 GB per concurrent recording | Writes audio straight to the content bucket under `meetings/` (`s3:PutObject` on `meetings/*`) |
| Redis 7 | ElastiCache `cache.t4g.micro` | Used only by LiveKit and Egress, not by the API |
| Whisper `whisper-server/` | ECS task, CPU (4 vCPU, `small`) or one GPU instance (`g4dn.xlarge`, `large-v3`) | Private only; the API calls it at `ASR_BASE_URL`. Arabic needs `large-v3` for good quality |
| Meeting assistant `meeting-bot/` | ECS Fargate service, 1 vCPU / 2 GB per task, one meeting per task | Outbound internet to Meet, Teams and Zoom; no inbound ports |

API environment (Secrets Manager for the secrets): `LIVEKIT_URL`, `LIVEKIT_API_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ASR_BACKEND=http`, `ASR_BASE_URL`, `ASR_API_KEY` (optional), `MEETING_BOT_VENDOR=self_hosted`, `MEETING_BOT_MAX_MINUTES`, `MEETING_UPLOAD_MAX_MB`. The API task role also needs `s3:GetObject` on `meetings/*` (to read recordings for transcription). LiveKit's webhook must reach `https://api.flobrain.ai/api/v2/livekit/webhook` (it is signed with the API secret).

Order: Redis, LiveKit + TLS, Egress, Whisper, then the assistant. Until each is set, the matching button in FloBrain answers "not set up" and nothing breaks.

### 3.13 Sovereign package (not for our AWS)

`deploy/sovereign/` (compose and a Helm chart, version 0.2.0: probes, autoscaling, ingress, network policies, and optional Whisper and meeting bot) is for customers who run FloBrain inside their own network with open models only. It is not meant for FloBrain's AWS account and changes nothing there. Its two settings, `AI_FORCE_PRIVATE_ONLY` and `AI_ALLOW_PLAINTEXT_HOSTS`, must stay unset on our deploy. The chart was checked with a stand-in renderer only; run `helm lint` and a test install before giving it to a customer.

### 3.14 Public status page

`python manage.py export_status` writes a cleaned-up `status.json` (public incidents and component states, no org data). Host it somewhere that does not depend on ECS, for example a public S3 object behind CloudFront, refreshed every minute by a scheduled task, and set `NEXT_PUBLIC_STATUS_JSON_URL` on Vercel to its address. Until then, the status page reads the API, which won't help during an API outage.

### 3.15 Demo environment (optional)

The demo (every role and feature working with sample data, `docs/v2/DEMO.md`) can run as its own small environment: one ECS service, its own small database, `DEMO_MODE=True`, `CREDENTIALS_ENCRYPTION_KEY` set, and `CONTENT_LOCAL_DIR` on the task's disk. In demo mode the scheduled commands run inside the web process (turn off with `DEMO_TICKS=0`), so it needs no worker or EventBridge rules. It must never share a database, bucket or secrets with production.

---

## 4. Questions for you

1. How were Django migrations run on production so far? We saw one `RunTask` on 2026-08-19.
2. Who created the us-east-2 resources and `GitHubActionsECSFargateRole`? Is that migration still planned?
3. Can staging go in the same account as production (separate VPC or service), or do you prefer a separate account?
4. Who owns the `flobrain.ai` DNS (needed for staging and any new HTTPS hostname)?
5. Do you prefer we propose CloudFormation changes as template diffs in the repo, or do you edit the stacks yourselves?
6. Is there a budget limit for the RDS upgrade and staging?
7. The Notion task "Switch FloBrain backend to unified AWS account (CloudFormation)" was marked Done on 7 Oct, but its checklist (audit, unified templates, move database, VPC and compute, failover test, CI from the new account, retire the old account) is still unticked. Which of those steps are finished? Our audit of 20 Oct still saw two accounts.
8. The multimodal team says (2 Oct meeting) part of their deploy pipeline was set up with credentials that belong to the FloBrain backend. Which credentials were they? Please rotate them once the multimodal service has its own role (S1, and `multimodalsupport.md` 4.4).

---

## 4b. Answers from Arsema (2026-10-21)

| Item | Answer | Next step | Status |
|---|---|---|---|
| S2, multimodal port 8000 | As far as she knows only the FloBrain backend calls the multimodal service. She agrees with limiting TCP 8000 to `98.89.195.180/32`. | Confirm with the team that nothing else calls it, CAIPO first, then change the rule. | Waiting for the CAIPO check |
| 3.5, migrations | Run by hand as a one-off ECS task (`aws ecs run-task`, `migrate` override). No pipeline step yet; planned. | Add a "migrate, then deploy" step to the pipeline (3.5). | Planned |
| S3, `SECRET_KEY` and `DB_PASS` | Moving them to Secrets Manager was planned, not done. | Move both to task-definition `secrets`, then rotate the DB password. Plan the `SECRET_KEY` rotation (it logs everyone out). | To do |
| S6, stopped `Flobrain-backend` EC2 | It was the interim backend before ECS. The ECS move is complete, so it is no longer needed. | Take a final snapshot, then terminate it. | Agreed, not done |
| S1, `GitHubActionsECSFargateRole` | Probably Lucas, who worked on automatic deploys from GitHub to AWS for the multimodal service; she created his user. She will confirm with him. | Confirm the owner, then fix the trust to the real repo with `StringEquals` and scope ECS permissions, or delete the role. | Waiting for Lucas |

She suggested going through the changes one at a time once they are confirmed. Nothing has been changed on AWS from our side.

## 5. Status log

| Date | What changed |
|---|---|
| 2026-10-20 | First version. Read-only audit of both accounts. Security items S1–S6. V2 deploy checklist. Phases 0–7c built locally, not deployed. |
| 2026-10-20 | Job worker (7g) built: `run_jobs` service, `JOBS_WORKER_ENABLED` switch. |
| 2026-10-20 | Vector store (7h) and knowledge ask (7i) built. To enable later: pgvector extension, embeddings env, AI provider key, worker service, then the org flag. No AWS change needed until then. |
| 2026-10-20 | Translation (7j) and BYOK (7k) built. BYOK will need one new secret, `CREDENTIALS_ENCRYPTION_KEY` (64 random hex), in Secrets Manager before it is turned on. |
| 2026-10-20 | Phase 8 built (buddies, approved actions, reports, skills, scheduled agents). Later need: a once-a-minute `manage.py tick_agents` task (EventBridge Scheduler → ECS RunTask) next to the worker service. Nothing to change today. |
| 2026-10-20 | Content Studio (Phase 9) built locally. When it is turned on it needs a private S3 media bucket and S3 permissions for the task role (`INFRA_CHANGES.md`). GPU workers run outside AWS (JarvisLabs) with presigned URLs only. |
| 2026-10-20 | Phase 14 built locally (public API, webhooks, MCP, status page). Later need: separate static hosting for `status.json` that does not depend on ECS, and two more once-a-minute commands (`tick_webhooks`, `tick_content`) next to `tick_agents`. |
| 2026-10-20 | Phase 17 built locally: org AI policy (private-only), plans and a verified Stripe webhook, SSO (OIDC) and SCIM, owner-only memory export, in-org marketplace, platform console with audited read-only support access, and a sovereign package for customer installs. New later needs: `STRIPE_WEBHOOK_SECRET`, `PUBLIC_API_BASE_URL`, `AI_SELF_HOSTED_HOSTS`, a daily `purge_exports` (3.11). Nothing to change today. |
| 2026-10-20 | **Final for handoff.** Phase 17 independent review fixed; 424 tests pass on SQLite and PostgreSQL 16. Nothing in this document has been applied to AWS. |
| 2026-10-21 | Self-hosted meetings (3.12), SAML sign-in, and the completion work (rooms, tasks, time, docs, people, AI admin, external agents, status page, billing checkout, Content Studio). New: the team to-do list (0), settings in 3.2, external services in 3.9, `tick_tasks` (3.11), status page hosting (3.14), demo environment (3.15). 757 tests pass on SQLite and PostgreSQL 16. Nothing has been applied to AWS. |
| 2026-10-21 | Checked against Notion: two new questions in section 4 (status of the unified-account task marked Done, and FloBrain credentials used by the multimodal pipeline). The new V2 site (`/v2`) and the new design are frontend only and need nothing from AWS. **Send this version.** Nothing has been applied to AWS. |
| 2026-10-21 | Arsema answered S1, S2, S3, S6 and the migrations question (4b). Growth round built locally: two more scheduled commands, `tick_automations` (every minute) and `run_data_reports` (hourly). Inbound webhooks for WhatsApp and Telegram (`/api/v2/hooks/...`) and a public website-chat endpoint will need the ALB to accept them when those features are turned on. Nothing has been applied to AWS. |
