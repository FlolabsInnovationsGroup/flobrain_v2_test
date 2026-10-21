# Sovereign package: "open models only" (Phase 17f)

A skeleton for running FloBrain V2 inside a customer's perimeter with no external model calls. Nothing here is applied to FloBrain's own AWS account. Review, pin images and test on a staging cluster before any customer install.

What the profile guarantees, and where it is enforced:

| Guarantee | Enforced by |
|---|---|
| Every org is `private_only` and cannot switch back | `AI_FORCE_PRIVATE_ONLY=True` (`brain.llm.policy`; `PUT /policy` returns 409 `locked`) |
| Only the in-cluster vLLM and BGE-M3 count as private | `AI_SELF_HOSTED_HOSTS=vllm,embeddings` |
| The legacy multimodal service, external APIs, external customer keys and external agents are refused with no network call | `check_ai` gate before every model call (17a) |
| Plain http is allowed only to those two in-cluster hosts | `AI_ALLOW_PLAINTEXT_HOSTS=vllm,embeddings` (everything else stays https-only) |
| Model servers and the database have no route out | compose `internal` network; Helm `NetworkPolicy` egress allowlist |
| Model weights are not downloaded at runtime | `HF_HUB_OFFLINE=1`; weights are loaded beforehand (step 2) |

Not covered yet: PII redaction (needs the detector service, Q25), SAML (17c TECH_DEBT), Content Studio GPU render workers (Phase 9 workers run separately), the website build.

## Files

- `docker-compose.open-models.yml`: one-host profile (db with pgvector, migrate, api on gunicorn, job worker, ticker, vLLM, TEI with BGE-M3).
- `Dockerfile.api` and `Dockerfile.api.dockerignore`: backend image with gunicorn and a non-root user. The hosted backend `Dockerfile` is not changed.
- `env.example`: every setting the profile needs. Copy to `.env`; never commit it.
- `helm/flobrain/`: Kubernetes chart (API with probes, HPA and PDB, worker, migrate hook, cron jobs, ServiceAccount, optional Ingress, network policies, optional Whisper and meeting bot). Database, vLLM and embeddings are separate releases. See "Runbook (Helm)" and "Helm values reference"; read "Validation status" before a customer install.

## Runbook (compose)

1. **Secrets.** `cp env.example .env`. Generate `SECRET_KEY` (64+ random characters), `AES_MASTER_KEY` and `CREDENTIALS_ENCRYPTION_KEY` (`openssl rand -hex 32` each), `DB_PASS`, `VLLM_API_KEY`. Set `AI_DIRECT_API_KEY` to the same value as `VLLM_API_KEY`. Keep the file readable only by the operator.
2. **Images and weights.** Pin `VLLM_IMAGE` and `TEI_IMAGE` by digest after testing them on the customer's GPUs. Load the chat model and `BAAI/bge-m3` into the `hf-cache` volume from a machine that may reach the model hub, then move the volume inside the perimeter. Check the model licence allows the customer's use.
3. **Model names.** Set `VLLM_MODEL` (hub id), `VLLM_SERVED_NAME`, and use the served name in `AI_DIRECT_MODEL_ALLOWLIST` and `AI_DIRECT_DEFAULT_MODEL`. `EMBEDDINGS_DIMENSION=1024` matches BGE-M3; changing the embedder means re-indexing.
4. **Start.** `docker compose -f docker-compose.open-models.yml up -d`. The `migrate` service creates the `vector` extension and runs migrations once; `api`, `worker` and `ticker` start after it succeeds.
5. **TLS.** Put the customer's reverse proxy in front of `127.0.0.1:8000` with their certificate. Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_BASE_URL` and `PUBLIC_API_BASE_URL` to the real names.
6. **First admin.** Create the first user through sign-up. Run `docker compose exec api python manage.py set_platform_admin <email>` only if the customer runs their own platform console (Django `createsuperuser` does not apply to V2 users).
7. **Verify private-only.** As an org owner: `GET /api/v2/orgs/{org}/policy` shows `inference_scope: private_only` and `locked_private_only: true`. Ask a knowledge question and confirm in the vLLM logs that the call arrived. From the `api` container, an outbound request to any public host must fail.
8. **Backups.** Back up the `pgdata` volume (or use the customer's managed PostgreSQL) and the three keys. Losing `CREDENTIALS_ENCRYPTION_KEY` makes stored SSO and BYOK secrets unreadable; losing `AES_MASTER_KEY` makes archives unreadable.

## Runbook (Helm)

Kubernetes 1.25+ (`policy/v1`, `autoscaling/v2`). A NetworkPolicy-enforcing CNI (Calico, Cilium) is needed for the network guarantees; without one the policies are silently ignored.

1. **Image.** Build `Dockerfile.api` from `flobrain-core/backend` (`docker build -f ../../deploy/sovereign/Dockerfile.api .` from that folder), push it to the customer's registry, and set `image.repository` and `image.tag` (`image.tag` is required; pin a digest with `tag@sha256:…`). Add `imagePullSecrets` if the registry needs credentials.
2. **Secret.** The chart never holds secret values; it only names an existing Secret:
   ```bash
   kubectl create namespace flobrain
   kubectl -n flobrain create secret generic flobrain-secrets \
     --from-literal=SECRET_KEY=… --from-literal=AES_MASTER_KEY=… --from-literal=CREDENTIALS_ENCRYPTION_KEY=… \
     --from-literal=DB_PASS=… --from-literal=AI_DIRECT_API_KEY=…
   # Meetings stack only (same value twice: Whisper checks WHISPER_API_KEY, the API sends ASR_API_KEY):
   #   --from-literal=WHISPER_API_KEY=$K --from-literal=ASR_API_KEY=$K --from-literal=MEETING_BOT_WORKER_TOKEN=fbw_…
   # Calls only: --from-literal=LIVEKIT_API_KEY=… --from-literal=LIVEKIT_API_SECRET=…
   ```
   Every key is loaded into the API, worker, cron and migrate pods with `envFrom`. Whisper and the bot read only their one key (`secretKeyRef`). A sealed-secrets or external-secrets controller works the same way: it just has to produce this Secret.
3. **Dependencies.** Deploy PostgreSQL with pgvector (label `app: flobrain-db`), vLLM (`app: vllm`, service `vllm:8000`) and TEI (`app: embeddings`, service `embeddings:80`) in the same namespace. If labels, ports or namespaces differ, change `networkPolicy.services` (add a `namespaceSelector` through `networkPolicy.extraEgress` for another namespace) and the host names in `config`. The `knowledge` migration runs `CREATE EXTENSION IF NOT EXISTS vector`, so the database user needs that right (or create the extension once as a superuser).
4. **Values.** Write `customer-values.yaml`: `image`, `config` (real host names, model names), `ingress` (host, class, TLS secret), sizes. Then:
   ```bash
   helm lint ./helm/flobrain -f customer-values.yaml
   helm template flobrain ./helm/flobrain -n flobrain -f customer-values.yaml > rendered.yaml   # review it
   helm upgrade --install flobrain ./helm/flobrain -n flobrain -f customer-values.yaml
   ```
   The migrate Job is a `post-install` / `pre-upgrade` hook. On first install the API pods start beside it; `/healthz` does not touch the database, so they report ready before the schema exists and requests fail until the Job finishes (usually under a minute). Wait for `kubectl -n flobrain wait --for=condition=complete job/flobrain-migrate` before opening the ingress to users.
5. **TLS and DNS.** With `ingress.enabled`, point the API host at the ingress controller. `ingress.tls[].secretName` is a `kubernetes.io/tls` Secret you create (`kubectl create secret tls flobrain-api-tls --cert=… --key=…`) or that cert-manager issues (set its issuer in `ingress.annotations`). Keep `networkPolicy.ingressFrom` matching the controller's namespace. Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_BASE_URL` and `PUBLIC_API_BASE_URL` to the real names.
6. **Check.** `kubectl -n flobrain get pods` (all `Running`/`Completed`), `kubectl -n flobrain logs job/flobrain-migrate`, then steps 6 and 7 of the compose runbook with `kubectl exec deploy/flobrain-api -- …`. From the API pod, an outbound request to any public host must time out.

### What the chart creates

| Object | Notes |
|---|---|
| `Deployment` + `Service` `<release>-api` | gunicorn on 8000, Service port `api.service.port` (80). Startup, liveness and readiness probes on `GET /healthz` (answered by `HealthCheckMiddleware` before host checks, no database call). Config checksum annotation restarts pods when `config` changes. |
| `Deployment` `<release>-worker` | `manage.py run_jobs`. No probe (no port; an exec probe would boot Django every period). `terminationGracePeriodSeconds` lets the current job finish after SIGTERM. |
| `HorizontalPodAutoscaler` (api, worker) | Off by default. CPU and optional memory targets; the Deployment drops `replicas` when its HPA is on. Needs metrics-server. |
| `PodDisruptionBudget` (api, worker) | API on (`minAvailable: 1`), worker off (one replica would block node drains). Set `maxUnavailable` instead of `minAvailable` if you prefer. |
| `CronJob` ×6 | `tick-agents`, `tick-webhooks`, `tick-content` (every minute), `tick-pulse` (every 5 min), `purge-exports` (03:17), `apply-retention` (02:41). `concurrencyPolicy: Forbid`. They replace the compose `ticker`. |
| `Job` `<release>-migrate` | Helm hook, `migrate --noinput`. |
| `ServiceAccount` | Token not mounted (`automountServiceAccountToken: false`); FloBrain never calls the Kubernetes API. Add annotations for workload identity if exports go to a cloud bucket. |
| `Ingress` | Optional (`ingress.enabled`), class, annotations, hosts and TLS secret from values. |
| `NetworkPolicy` | `-egress` (API/worker/cron/migrate: DNS, `networkPolicy.services`, Whisper when on, `extraEgress`), `-default-deny-ingress` (every pod of the release), `-ingress` (API only, from `ingressFrom` and the bot), plus `-whisper` and `-meeting-bot` when those are on. |
| `ConfigMap` `<release>-config` | `config` as env. With Whisper on it adds `ASR_BACKEND=http`, `ASR_BASE_URL=http://<release>-whisper:8000` (and `ASR_MODEL`); with the bot on, `MEETING_BOT_VENDOR=self_hosted`. A key you set in `config` always wins. |

Security on every pod: `runAsNonRoot`, uid/gid 10001, `seccompProfile: RuntimeDefault`, no privilege escalation, all capabilities dropped, read-only root filesystem with `/tmp` (and for Whisper the model cache, for the bot `$HOME` and `/dev/shm`) on volumes.

### Meetings stack (optional)

The same services as `deploy/meetings`, both off by default:

- **Whisper** (`meetings.whisper.enabled`): Deployment + ClusterIP Service `<release>-whisper:8000`, probes on `/health`. Reachable only from this release's API, worker and cron pods; its own egress is DNS only. Model weights live on a PVC (`persistence`, kept on uninstall). With `offline: true` (`HF_HUB_OFFLINE=1`) the weights must be on the volume first: run the pod once with `offline: false` and `extraEgress` to the model hub, or copy the cache in. For a GPU, build the CUDA variant (see `whisper-server/Dockerfile`), set `device: cuda`, add `nvidia.com/gpu: 1` to `resources.limits` and GPU `nodeSelector`/`tolerations`.
- **Meeting bot** (`meetings.meetingBot.enabled`): Deployment, one meeting per pod at a time, scale with `replicas`. Issue its token with `manage.py worker_token --issue meeting-bot-1 --kind meeting_bot` and put it in the Secret. By default it calls the API inside the cluster (`http://<release>-api`); set `apiUrl` to go through the public name instead. Its egress is DNS, the API, and `meetings.meetingBot.egress` (default: any address outside private ranges, because Zoom, Meet and Teams are on the internet). This is the one pod that is meant to reach the internet; leave it off for a fully closed install. `/dev/shm` is a memory volume (`shmSize`, the compose `shm_size`).

**LiveKit and Egress stay outside the chart.** WebRTC media needs UDP 50000–50100 (and TCP 7881) reachable directly by every participant, with the node's public address advertised to clients. On Kubernetes that means `hostNetwork: true` (or one NodePort/LoadBalancer per UDP port), one LiveKit pod per node, and node firewall rules, which conflict with this chart's non-root, no-host-access, default-deny pods and with HPA-style scaling. Egress also needs `SYS_ADMIN` (room composite recording) and Redis. Run them with `deploy/meetings/docker-compose.yml` on dedicated hosts, or with LiveKit's own Helm charts on a dedicated node pool, then set `LIVEKIT_URL`, `LIVEKIT_API_URL` in `config`, the key and secret in the Secret, and allow the API to reach `LIVEKIT_API_URL` with `networkPolicy.extraEgress`.

### Helm values reference

| Key | Default | Meaning |
|---|---|---|
| `image.repository` / `tag` / `pullPolicy` | `registry.internal.example/flobrain-api` / `""` (required) / `IfNotPresent` | API image (also worker, cron, migrate). |
| `imagePullSecrets` | `[]` | Registry credentials. |
| `existingSecret` | `flobrain-secrets` | Secret loaded with `envFrom`. Required. |
| `serviceAccount.create` / `name` / `annotations` / `automountToken` | `true` / release name / `{}` / `false` | `create: false` + `name` uses an existing account (`default` if empty). |
| `podSecurityContext` | non-root 10001, `fsGroup` 10001, `RuntimeDefault` seccomp | Every pod. |
| `containerSecurityContext` | no escalation, read-only root, drop `ALL` | API-image and Whisper containers (the bot has its own toggle). |
| `nodeSelector` / `tolerations` / `affinity` | empty | API, worker, cron, migrate pods. |
| `api.replicas` | `2` | Ignored when `api.autoscaling.enabled`. |
| `api.resources` | req 500m / 1Gi, limit 2 CPU / 2Gi | |
| `api.probes.path` | `/healthz` | `startup`, `liveness`, `readiness` hold `periodSeconds`, `failureThreshold`, `timeoutSeconds`. |
| `api.service.type` / `port` | `ClusterIP` / `80` | |
| `api.autoscaling.*` | off, 2–6, CPU 70 %, memory unset | `targetMemoryUtilizationPercentage` adds a memory metric. |
| `api.podDisruptionBudget.*` | on, `minAvailable: 1` | Or `maxUnavailable`. |
| `api.podAnnotations` / `worker.podAnnotations` | `{}` | E.g. scraping annotations. |
| `worker.replicas` / `resources` / `terminationGracePeriodSeconds` | `1` / req 250m / 1Gi, limit 2 CPU / 2Gi / `300` | |
| `worker.autoscaling.*` / `worker.podDisruptionBudget.*` | off, 1–4, CPU 70 % / off | Jobs are claimed from the database, so extra workers are safe. |
| `migrate.resources` | req 250m / 512Mi, limit 1Gi | |
| `cronjobs.enabled` | `true` | Turn off only if something else runs the tick commands. |
| `cronjobs.jobs.<name>.schedule` / `command` | see "What the chart creates" | `command` is a `manage.py` command. |
| `cronjobs.startingDeadlineSeconds` / `activeDeadlineSeconds` / `successfulJobsHistoryLimit` / `failedJobsHistoryLimit` / `resources` | `120` / `1800` / `1` / `3` / req 100m / 512Mi | |
| `ingress.enabled` / `className` / `annotations` | `false` / `""` / `{}` | |
| `ingress.hosts[].host` / `paths[].path` / `pathType` | `api.flobrain.internal.example`, `/`, `Prefix` | All paths go to the API Service. |
| `ingress.tls[].secretName` / `hosts` | `flobrain-api-tls` | Existing TLS Secret (or cert-manager's). |
| `config.*` | see `env.example` | Non-secret env. Never put a secret here. |
| `networkPolicy.enabled` | `true` | |
| `networkPolicy.dns.podLabels` | `k8s-app: kube-dns` | CoreDNS labels in any namespace. |
| `networkPolicy.services[]` | database 5432, vllm 8000, embeddings 80 | `name`, `podLabels`, `port`; same namespace. |
| `networkPolicy.extraEgress` | `[]` | Raw egress rules for the API/worker/cron (IdP, object storage, LiveKit). |
| `networkPolicy.ingressFrom` | `ingress-nginx` namespace | Raw `from` peers allowed to the API on 8000. |
| `meetings.whisper.enabled` | `false` | |
| `meetings.whisper.image.*` / `replicas` | `registry.internal.example/flobrain-whisper`, tag required / `1` | Built from `whisper-server/`. |
| `meetings.whisper.model` / `device` / `computeType` / `asrModel` | `small` / `cpu` / `int8` / `""` | `WHISPER_*`; `asrModel` sets the API's `ASR_MODEL`. |
| `meetings.whisper.offline` | `true` | `HF_HUB_OFFLINE=1`. |
| `meetings.whisper.apiKeySecret.name` / `key` | `existingSecret` / `WHISPER_API_KEY` | |
| `meetings.whisper.persistence.*` | on, 10Gi, default class, no existing claim | Model cache. Off = `emptyDir` (downloads on every start). |
| `meetings.whisper.resources` / `nodeSelector` / `tolerations` / `affinity` / `extraEgress` | req 1 CPU / 2Gi, limit 4 / 6Gi / empty | |
| `meetings.meetingBot.enabled` | `false` | |
| `meetings.meetingBot.image.*` / `replicas` | `registry.internal.example/flobrain-meeting-bot`, tag required / `1` | Built from `meeting-bot/`. |
| `meetings.meetingBot.apiUrl` / `pollSeconds` | in-cluster API / `10` | `FLOBRAIN_API_URL`, `POLL_SECONDS`. |
| `meetings.meetingBot.tokenSecret.name` / `key` | `existingSecret` / `MEETING_BOT_WORKER_TOKEN` | |
| `meetings.meetingBot.shmSize` / `readOnlyRootFilesystem` | `1Gi` / `true` | Set `readOnlyRootFilesystem: false` if PulseAudio or Xvfb fail to start. |
| `meetings.meetingBot.resources` / `nodeSelector` / `tolerations` / `affinity` | req 1 CPU / 1.5Gi, limit 2 / 3Gi | |
| `meetings.meetingBot.egress` | internet outside RFC 1918 / link-local | Raw egress rules. |

### Validation status

`helm` could not be downloaded in the build environment (get.helm.sh and the Go module proxy were blocked), so **`helm lint` has not been run**. The templates were rendered with a stand-in (Go `text/template` plus the few Sprig functions the chart uses) for the defaults, everything on, everything off, an existing claim and the failure cases (missing image tag, missing secret name), and the output was parsed as YAML and checked for selectors, probe ports, service/ingress/HPA/PDB targets, security contexts and resources. Not checked: Kubernetes schema validation, a real cluster, the Whisper and bot images running under uid 10001 with a read-only root (their writable paths are volumes, but this has not been run). Run `helm lint` and `helm template … | kubeconform -strict` before the first customer install.

## Upgrades

Take a database backup, bump the image tag, run the migrate job (compose: `docker compose run --rm migrate`), then restart `api`, `worker` and `ticker`. With Helm, `helm upgrade` with the new `image.tag` runs the migrate hook before the Deployments roll. Never edit the lock (`AI_FORCE_PRIVATE_ONLY`) on a running customer install without the customer's written approval.
