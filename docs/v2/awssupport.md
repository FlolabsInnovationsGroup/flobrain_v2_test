# FloBrain AWS: how it runs today, and what V2 needs

**To:** Arsema, Lucas (AWS / DevOps)
**From:** FloBrain team
**Status:** Living document. It lives in `docs/v2/awssupport.md` and is updated as V2 is built. The final version is sent when the V2 code is ready.
**Last update:** 2026-10-20

Nothing in this document has been applied to AWS. Everything came from read-only audits (Describe/List/Get only). The detailed engineering source is `docs/v2/INFRA_CHANGES.md`. This file is the human summary of it.

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
| `CREDENTIALS_ENCRYPTION_KEY` | not set | Customer API keys (BYOK) cannot be stored | A random 32-byte key in Secrets Manager |
| `MULTIMODAL_API_KEY` | not set | Calls to the multimodal service carry no key | The key the multimodal team issues (`multimodalsupport.md`, step 3) |
| Platform AI provider key (name to be confirmed in `INFRA_CHANGES.md`) | none | The V2 AI features (`direct` provider) stay "Not configured" | An OpenAI (or other) key in Secrets Manager, never plain text |

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

Production does **not** run migrations on container start today, and we could not find how past migrations were run. **Please tell us.** For V2:
- run one **one-off ECS task** (same image, same env, `python manage.py migrate --noinput`),
- start or update the web service only after it exits 0,
- never run `migrate` inside every web task.

### 3.6 Background worker

V2 uses a PostgreSQL-backed job queue (no Redis, no SQS). It needs **one more ECS service** from the same image, running:

```
python manage.py run_jobs
```

It has no public port and no ALB, and uses the same database and secrets. Until it exists, background features (indexing, transcription jobs) show "unavailable".

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

### 3.10 Rough monthly cost impact (to confirm with AWS Pricing Calculator)

- Staging environment (ECS + small RDS): about the same as the current production stack.
- Worker service: one more small Fargate task.
- Larger RDS class and Multi-AZ: the main cost increase.
- Secrets Manager: a small per-secret monthly charge.

---

## 4. Questions for you

1. How were Django migrations run on production so far? We saw one `RunTask` on 2026-08-19.
2. Who created the us-east-2 resources and `GitHubActionsECSFargateRole`? Is that migration still planned?
3. Can staging go in the same account as production (separate VPC or service), or do you prefer a separate account?
4. Who owns the `flobrain.ai` DNS (needed for staging and any new HTTPS hostname)?
5. Do you prefer we propose CloudFormation changes as template diffs in the repo, or do you edit the stacks yourselves?
6. Is there a budget limit for the RDS upgrade and staging?

---

## 5. Status log

| Date | What changed |
|---|---|
| 2026-10-20 | First version. Read-only audit of both accounts. Security items S1–S6. V2 deploy checklist. Phases 0–7c built locally, not deployed. |
