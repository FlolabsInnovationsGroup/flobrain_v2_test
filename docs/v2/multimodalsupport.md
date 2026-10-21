# Multimodal Perception Service: what FloBrain needs from you

**From:** FloBrain team
**To:** Multimodal team (owners of `FlolabsInnovationsGroup/multi-modal-perception`)
**Date:** 2026-10-21 (first sent 2026-10-20)
**Status:** Final for handoff. Request: FloBrain will not change your repository or your server. Everything below is for your team to decide and build.
**Living document:** it lives in FloBrain's `docs/v2/multimodalsupport.md` and is updated as V2 is built. The final version is sent when the V2 code is ready. See the status log at the end.

---

## 1. Why you are getting this

FloBrain V1 sends every chat message to your service. FloBrain V2 is being built now and will need more from it. We reviewed your `main` branch (commit `1d875b8`) and did a read-only AWS check. Nothing was changed.

Two things matter right away:

1. **The service is open to the whole internet with no authentication, and it holds the OpenAI key.** Anyone who finds the IP can use your OpenAI account and run up the bill.
2. **Some of its behavior silently breaks FloBrain features.** Token counts are always 0, failures look like normal answers, and answers are cut at 256 tokens.

Section 3 lists what we found. Section 4 lists what we are asking for, in priority order, with how to do each item and how we will check it. Section 5 gives a rollout order that never breaks FloBrain V1.

> Note: we read `main`. The EC2 host may run a different commit. Please confirm which commit is deployed before you start.

---

## 2. How FloBrain uses the service today

```
Browser → api.flobrain.ai (Django on ECS, main AWS account)
        → NAT gateway 98.89.195.180
        → http://35.153.90.219:8000/process   (EC2 "multi-modal-perception", second AWS account)
        → OpenAI gpt-4o-mini
```

What Django sends on every V1 chat message:

- `POST /process`, `multipart/form-data`, a single field `text_input`.
- `text_input` is the whole conversation flattened into one string: `System: You are FloBrain, a helpful AI assistant.`, then `User: ...` / `Assistant: ...` lines, oldest first.
- A `model` form field when the user picked one (your service ignores it).
- `Authorization: Bearer <MULTIMODAL_API_KEY>` **only if** that variable is set. It is **not set** in production today.

What Django reads back: `result`, `model`, `file_type`, `total_tokens`.

How V1 handles your errors:

- **HTTP error with a JSON body:** shown to the user as an assistant message starting with `Error:`. The request does not crash.
- **Non-JSON body:** the request fails with 500, and the user's message is saved with no reply.
- **HTTP 200 with the "Echoing input" text:** shown as if it were a real answer.

**So any error you return must be JSON with a non-200 status.** That is safe for V1.

---

## 3. What we found

| # | Finding | Impact | Severity |
|---|---|---|---|
| F1 | Port 8000 is open to `0.0.0.0/0`. No authentication. `MULTIMODAL_API_KEY` is never checked. | Anyone can use your OpenAI key. | 🔴 Critical |
| F2 | Plain HTTP, no TLS. The request crosses the public internet between two AWS accounts. | User conversations travel unencrypted. | 🔴 High |
| F3 | When the OpenAI call fails, the service returns **HTTP 200** with `Perception system temporarily unavailable. Echoing input: <the user's full text>`. | FloBrain stores and shows this as a real answer. The echoed text is the whole flattened conversation. | 🟠 High |
| F4 | An in-memory response cache keyed by the lowercased message. Shared by all users, never expires, no size limit. | Memory grows until the process restarts or crashes on a 2 GB t3.small. Identical inputs from different users get the same cached answer. | 🟠 High |
| F5 | `total_tokens` is computed but **not returned**. | FloBrain records 0 tokens for every call. Usage and cost tracking cannot work. | 🟠 Medium |
| F6 | `max_tokens=256` by default. | Longer answers are cut mid-sentence. | 🟡 Medium |
| F7 | A fixed system prompt ("fast, concise multimodal perception assistant ... operational analysis") is prepended to FloBrain's own system line. | Two conflicting personas, so answers are shorter and stranger than intended. | 🟡 Medium |
| F8 | Only `text_input` and `audio_file` are accepted: no structured `messages[]`, no model choice, no images. Audio is transcribed and then answered, and the transcript is not returned. | V2 cannot use history properly, choose models, or get a transcript. | 🟡 Medium |
| F9 | No logs in CloudWatch, no SSM agent, unencrypted 8 GB root volume, no IAM role. A single t3.small with no health monitoring. | Outages and abuse are invisible. | 🟡 Medium |
| F10 | The planned ECS move in the main account (us-east-2) is unfinished and its CI cannot work. Details are in 4.4. | No safe deploy path. | 🟡 Medium |
| F11 | `generate_response` catches every exception, including programming bugs, and hides it as the echo text. | Bugs look like provider outages. | 🟡 Low |

---

## 4. What we are asking for

Priorities:
- **P0:** this week.
- **P1:** needed before FloBrain V2 AI features ship.
- **P2:** nice to have.

**Rule for every item:** keep `POST /process` backwards compatible. Add fields, never remove or rename the ones V1 reads.

### 4.1 P0: security (this week)

#### P0-1. Close the port to the world (ops, about 5 minutes, no code)

- In the security group of the `multi-modal-perception` EC2 (`launch-wizard-2`), change the inbound rule for TCP 8000 from `0.0.0.0/0` to **`98.89.195.180/32`**. That is FloBrain's NAT gateway, the only caller that should reach it.
- Keep SSH (22) restricted as it is now.
- If anything else calls this service (testing, Jarvis, other apps), tell us first and add its IP as a separate rule. Do not reopen it to the world.
- Check the OpenAI usage dashboard for unexpected traffic, and set a monthly spend limit on that OpenAI project.

**Done when:** a request to `http://35.153.90.219:8000/health` from any other IP times out, and FloBrain chat still works.

#### P0-2. API key authentication (code)

Accept `Authorization: Bearer <key>` and compare in constant time. Support several keys, so you can rotate without downtime.

Ship it in **two steps** so V1 never breaks:

1. `REQUIRE_API_KEY=false`: check the key, log the result (never log the key itself), and still allow the call.
2. After FloBrain confirms it is sending the key: set `REQUIRE_API_KEY=true`. Now a missing or wrong key returns 401.

```python
# api/auth.py
import hmac, logging, os
from fastapi import Header, HTTPException

log = logging.getLogger(__name__)
_KEYS = [k.strip() for k in os.getenv("MULTIMODAL_API_KEYS", "").split(",") if k.strip()]
_REQUIRE = os.getenv("REQUIRE_API_KEY", "false").lower() == "true"

async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    ok = bool(token) and any(hmac.compare_digest(token, k) for k in _KEYS)
    if ok:
        return
    log.warning("multimodal auth: missing or invalid key")  # never log the token
    if _REQUIRE:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid API key"})
```

Add `dependencies=[Depends(require_api_key)]` to every router except `GET /health`.

- **Key generation:** at least 32 random bytes (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- **Sharing the key:** send it to the FloBrain DevOps owner privately, never in chat, email or the repo.
- **FloBrain's side:** we put the key in `MULTIMODAL_API_KEY`. Django already sends the Bearer header when that variable is set.

**Done when:**
- No key → 401.
- Wrong key → 401.
- Correct key → 200.
- `/health` works without a key.
- The key never appears in logs.

#### P0-3. Stop returning HTTP 200 on failure (code)

Remove the `except Exception: return "Perception system temporarily unavailable. Echoing input..."` block. Let OpenAI errors reach the route and map them to real status codes with a JSON body.

| OpenAI error | Status | `code` |
|---|---|---|
| `openai.RateLimitError` | 429 | `rate_limited` |
| `openai.APITimeoutError` | 504 | `provider_timeout` |
| `openai.APIConnectionError` | 502 | `provider_unavailable` |
| `openai.APIStatusError` with status ≥ 500 | 502 | `provider_unavailable` |
| `openai.AuthenticationError` / `PermissionDeniedError` | 500 | `misconfigured` (alert on this: it is your key) |
| `openai.BadRequestError` | 400 | `invalid_request` |
| Anything else | 500 | `internal_error` (log the stack trace) |

The body is always JSON:

```json
{"error": {"code": "provider_timeout", "message": "Upstream model timed out", "request_id": "..."}}
```

Never put the user's text in an error body.

**Done when:** an OpenAI outage returns a non-200 JSON error. FloBrain V1 then shows `Error: ...` instead of a fake answer.

#### P0-4. Remove the shared cache (code)

Delete `self._cache` from `UltraFastOpenAIService`. Chat answers depend on the full conversation, so caching by message text is wrong. It also mixes users and grows without limit.

If you want caching later, it must be:
- keyed by (API key or caller id, model, hash of the full request),
- bounded in size (for example `cachetools.TTLCache(maxsize=1000, ttl=300)`),
- and off by default.

**Done when:** memory stays flat under a load test of 10,000 different messages.

### 4.2 P1: contract (before V2 AI features)

#### P1-1. Return token usage on `/process` (small, fixes V1 right away)

Add these fields to `PerceptionOutput`. All are optional, and the existing fields stay:

```python
class PerceptionOutput(BaseModel):
    result: str
    model: str
    file_type: Literal["text", "audio", "image", "video"]
    total_tokens: int | None = None       # V1 already reads this field
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    request_id: str | None = None
```

Fill them from `response.usage`. Return `null` when unknown, never a fake 0.

**Done when:** FloBrain's usage records show real token counts.

#### P1-2. Make the answer length and system prompt configurable (no code: env vars already exist)

- Set `OPENAI_MAX_TOKENS` to at least `1024` in the deployed environment (today it defaults to 256).
- Set `OPENAI_SYSTEM_PROMPT` to something neutral (for example `"You are a helpful assistant."`), or let the caller's system message take over. FloBrain already sends its own system line.

**Done when:** a long answer is no longer cut at 256 tokens, and FloBrain answers no longer sound like an "operational perception" tool.

#### P1-3. An OpenAI-compatible chat endpoint (main V2 need)

Add `POST /v1/chat/completions` with the same request and response shape as OpenAI's Chat Completions API. That way FloBrain V2's provider client (and any OpenAI SDK) works with your service by changing only the base URL.

Request:

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 1024,
  "temperature": 0.4,
  "stream": false
}
```

Rules:
- **Model allowlist** from config, for example `ALLOWED_MODELS=gpt-4o-mini,gpt-4o`. Any other model → 400 `model_not_allowed`.
- **Limits:** cap `max_tokens` at a configured maximum and the request body size (for example 1 MB). Reject more than N messages.
- **Messages:** pass `messages` through as given. Do not prepend your own system prompt when the caller sends one.
- **Response:** the OpenAI shape, including `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`, plus an `x-request-id` header.
- **Errors:** the same table as P0-3, in the OpenAI error format: `{"error": {"message", "type", "code"}}`.
- **Streaming (`stream: true`, SSE):** P2. Accept the field and return 400 `stream_not_supported` until it is built.

If you later serve self-hosted models on JarvisLabs (MiniCPM, Qwen through vLLM or Ollama), keep this same contract. FloBrain then needs no change.

#### P1-4. A transcription-only endpoint (now optional for FloBrain)

**Update 2026-10-21:** FloBrain no longer needs this for meetings. Meeting transcripts now run on FloBrain's own Whisper server (`whisper-server/`, faster-whisper) inside FloBrain's network, so meeting audio never leaves it. Build this only if other callers need it. If you do, keep the shape below so FloBrain could use it as a fallback later.

Add `POST /v1/audio/transcriptions`, OpenAI-compatible: multipart `file`, plus optional `model` and `language`. It returns `{"text": "..."}`, plus `duration_seconds` and `request_id`.

- Validate the file type (wav, mp3, m4a, webm, ogg, flac) and size (≤ 25 MB, the OpenAI upload limit). Anything else → 400.
- Do not answer the audio. Return only the transcript.

If FloBrain ever uses it, it would be for voice input, and we would compare it with our Whisper server on an Arabic and English word-error-rate set, so a `language` hint matters.

#### P1-5. HTTPS, or no public exposure at all

Pick one. We recommend **option A**.

- **Option A (recommended): run the service inside FloBrain's private network.** Deploy it as an ECS Fargate service in the **main account, us-east-1, same VPC as FloBrain**, behind an **internal** load balancer (or ECS Service Connect / Cloud Map). It gets no public IP and no public port.
  - TLS on the internal ALB is still recommended; an ACM private certificate or a cert for an internal hostname both work.
  - Benefits: lower latency, no cross-account internet hop, IAM roles and Secrets Manager for the OpenAI key, CloudWatch logs for free.
  - This is close to the plan already started in us-east-2. We suggest us-east-1 instead, so the service sits next to FloBrain. See 4.4 for what to fix first.
- **Option B: keep the EC2, add TLS.** Put Caddy or nginx in front with a certificate for a hostname such as `perception.flobrain.ai`. That needs a DNS record from whoever manages the `flobrain.ai` domain. Keep the security group limited to the NAT IP, and keep the API key.

**Done when:** FloBrain calls the service over `https://`, or only from inside the private network, and nothing answers on a public plain-HTTP port.

#### P1-6. Logging and health

- **Structured JSON logs to CloudWatch:** request_id, route, status, latency, model, tokens, and the caller key id (not the key itself).
- **Never log user text or transcripts** by default. Allow it only with a debug flag that is off in production.
- **`GET /health`:** returns 200 when the process is up. Add `GET /health/ready`, which also checks that the OpenAI key is configured, but without calling OpenAI on every check.
- **Alarms:** 5xx rate, p95 latency, `misconfigured` errors, and OpenAI spend.

### 4.3 P2: nice to have

- Streaming (SSE) on `/v1/chat/completions`, for faster voice and chat replies.
- Image input in `messages` (OpenAI `image_url` content parts), with a size limit.
- A per-key rate limit (for example 60 requests per minute per key) returning 429.
- A `GET /v1/models` endpoint listing the allowlisted models. FloBrain uses it to validate configuration.
- A non-root container user, a pinned base image, and dependency pinning in `requirements.txt`.

### 4.4 Fix the deployment pipeline before using it

We found this in the main account, us-east-2. Nothing there is running, so it is harmless today.

| Item | Today | Fix |
|---|---|---|
| IAM role `GitHubActionsECSFargateRole` trust | `repo:multi-modal-perception/autodeploy:ref:refs/heads/main` | `repo:FlolabsInnovationsGroup/multi-modal-perception:ref:refs/heads/main`, with `StringEquals` |
| GitHub OIDC identity provider | Not registered in the account, so the role can never be used | Register it **only after** the trust above is fixed. Registering it first would let anyone who creates a GitHub account named `multi-modal-perception` assume this role |
| Role permissions | `ecs:RegisterTaskDefinition`, `UpdateService`, `DescribeTaskDefinition` on `*`, which includes FloBrain's production service | Scope to the multimodal cluster and service ARNs. `DescribeTaskDefinition` on `*` can read FloBrain's plain-text secrets |
| ECR repository name | The task definition uses `multi-modal-perception-repo`; the repo that exists and the IAM policy use `multi-modal-perception` | Use one name everywhere |
| Image tag | `:latest` in the task definition | The workflow already tags by commit SHA. Keep that, and never deploy `:latest` |
| OpenAI key | Expected in Secrets Manager `multi-modal-perception/openai-api-key` (us-east-2) | Fine. Move it to the same region as the service, and rotate it after the move |
| Region | us-east-2, while FloBrain is in us-east-1 | Prefer us-east-1 (option A in P1-5) |

There are also two empty ECS clusters there (`multi-modal-perception-cluster`, `my-app-cluster`). Tell us if they are still needed.

---

## 5. Rollout order (V1 keeps working at every step)

| Step | Who | What | V1 impact |
|---|---|---|---|
| 1 | Multimodal ops | P0-1: security group to `98.89.195.180/32`. Set an OpenAI spend limit. | None |
| 2 | Multimodal | P0-3 (real errors), P0-4 (no cache), P1-1 (tokens), P1-2 (env: `OPENAI_MAX_TOKENS`, `OPENAI_SYSTEM_PROMPT`). Deploy. | Better: real errors show as `Error: ...`, token counts appear, longer answers |
| 3 | Multimodal | P0-2 with `REQUIRE_API_KEY=false`. Share one key privately with FloBrain DevOps. | None |
| 4 | FloBrain | Set `MULTIMODAL_API_KEY` on the FloBrain ECS task. Confirm the logs show "valid key" for all calls. | None |
| 5 | Multimodal | Set `REQUIRE_API_KEY=true`. | None (FloBrain already sends the key) |
| 6 | Multimodal | P1-3 `/v1/chat/completions`, P1-4 `/v1/audio/transcriptions`, P1-6 logging. | None (new endpoints) |
| 7 | Both | P1-5 option A (or B) and the 4.4 pipeline fixes. FloBrain switches `MULTIMODAL_SERVICE_URL` to the new private or HTTPS address. | Short switch, tested in staging first |
| 8 | Multimodal | Retire the old EC2 once traffic is moved. Rotate the OpenAI key. | None |

Please tell us before steps 5 and 7, so we can watch FloBrain while you switch.

---

## 6. What FloBrain will and will not send you

- **Now:** V1 chat text (`text_input`), and later an API key.
- **After P1-3 and P1-5:** structured messages from FloBrain V2 features.
- **Never:** customer API keys (BYOK), passwords, or tokens. FloBrain V2 handles customer keys itself.
- **Not until HTTPS (or private networking) and authentication are in place:** organization documents, memory, or files. FloBrain V2 is built to block this in code until then.

---

## 7. Acceptance checklist

FloBrain will run this checklist against the deployed service:

- [ ] Port 8000 is unreachable from the public internet (except FloBrain's NAT IP, or nothing at all with option A).
- [ ] No key → 401. Wrong key → 401. Valid key → 200. `/health` works without a key.
- [ ] OpenAI failure → non-200 JSON error. No "Echoing input" text anywhere.
- [ ] `/process` returns `total_tokens`, `prompt_tokens`, `completion_tokens` (or `null`).
- [ ] Answers longer than 256 tokens are not cut off.
- [ ] Memory stays flat after 10,000 different requests (no shared cache).
- [ ] `/v1/chat/completions` works with the official OpenAI Python SDK by setting `base_url` and `api_key`. Disallowed model → 400.
- [ ] (Only if you build P1-4) `/v1/audio/transcriptions` returns only the transcript and rejects files over 25 MB.
- [ ] Logs contain request_id, status, latency and tokens, and never user text or keys.
- [ ] The traffic is HTTPS or private-network only.

---

## 8. Questions for your team

1. Which commit is deployed on the EC2 today? Is it `main` at `1d875b8`?
2. Does anything besides FloBrain call the service (testing, Jarvis, CAIPO, other apps)? CAIPO is planned to go through FloBrain, not call you directly.
3. Who owns the OpenAI account and the key, and is there a spend limit today?
4. Is the us-east-2 ECS plan still active? Who set it up?
5. Do you plan to serve self-hosted models (MiniCPM in `minicpm_test_case/`) on JarvisLabs through this service? If yes, please keep the OpenAI-compatible contract from P1-3.
6. Which option for P1-5 do you prefer, A (private ECS in the main account) or B (EC2 with TLS)?
7. Which FloBrain backend credentials did your deploy pipeline use (2 Oct meeting)? They need rotating once your own role exists.
8. Do you agree that FloBrain keeps customer keys and calls providers itself (section 10)? If CAIPO or another product needs your service to use customer keys, tell us which one, so we can agree a contract for that product only.

Thank you. Reply with your plan and dates per step, and we will align FloBrain's side.

---

## 9. FloBrain side: what is already built (local, not deployed)

| Item | Status |
|---|---|
| FloBrain treats the "Echoing input" HTTP 200 body as an error in V2, and never stores it as an answer | Built (Phase 7a) |
| V2 stores unknown token counts as unknown (not 0) | Built (Phase 7a) |
| V2 has an OpenAI-compatible client (`direct`) with a model allowlist and real error mapping. It can point at your `/v1/chat/completions` once P1-3 exists | Built (Phase 7b) |
| V2 sends no organization documents, memory, files, other members' messages or credentials to the multimodal service | Enforced by design (Decision E29) |
| Knowledge ask (org documents and room messages) uses only the `direct` provider. Without it the feature returns "Not configured" and never calls the multimodal service | Built (Phase 7i), with a test that the legacy adapter is not called |
| Live translation of room messages uses only the `direct` provider. Without it the feature returns "Not configured" and never calls the multimodal service | Built (Phase 7j), with a test that the legacy adapter is not called |
| Customer AI keys (BYOK) are never sent to the multimodal service; a test checks the legacy request body, headers and logs | Built (Phase 7k) |
| Orgs can choose "private only" AI (Phase 17a). For those orgs FloBrain refuses the multimodal service before any network call, because it is not a self-hosted model host we control end to end | Built, with a test that no call is made |
| The sovereign package for customer installs (Phase 17f) runs open models in the customer's own network and does not use the multimodal service at all | Built (skeleton) |
| Meetings (calls inside FloBrain on our own LiveKit server, and our own bot for Zoom, Meet and Teams) are transcribed by FloBrain's own Whisper server. Meeting audio, transcripts and summaries never go to the multimodal service | Built (2026-10-21), with tests |
| Meeting summaries, action items and Ask over meeting transcripts use only the `direct` provider | Built (2026-10-21) |
| Pulse routing: when a `direct` provider fails or is unhealthy, FloBrain tries the next allowed provider. The multimodal service is never a failover target | Built (2026-10-21), with tests |
| SAML sign-in, personal insights and the rest of the 2026-10-21 work never call the multimodal service | Built (2026-10-21) |
| V1 path to `/process` | Unchanged |

## 10. Your provider-integration plan (B1 to B7): FloBrain's answers

Your Notion pages "02 Delivery plan" and "03 Architecture, technical design and integration boundary" (Integrate AI providers, revision 2.1, 19 Sep 2026) leave B1 to B7 open and wait for the FloBrain backend. These are the answers from the V2 code as it is today.

**The short version:** FloBrain V2 keeps customer keys (BYOK) itself and calls the providers itself. It will not hand a customer key to the multimodal service, and it will not build a key-reading interface for you. So **your T5 (live credential reader) is not needed for FloBrain**. Your M1 module (T1 to T4) is still useful: as the clean provider layer behind P1-3, for CAIPO and robotics, and for self-hosted models (MiniCPM). Please run it with **platform keys you own**, not customer keys.

| ID | Your question | FloBrain V2 answer |
|---|---|---|
| B1 | Where are keys stored, and how does multimodal read them? | In FloBrain's own database (`integrations.AICredential`), encrypted with AES-256-GCM, the credential id and org id bound in, with a `key_version` for rotation (Decision E20). Keys are never returned by any API, to people or to services. There is no direct database read and no backend-mediated readback for multimodal. |
| B2 | Scope, binding, customer or platform source, who authorizes | Scope is the organization, plus the person for personal keys (empty owner = org key, used by owners and admins; Q41 decides if members may use org keys). FloBrain authorizes every call (`can()`, the `byok` feature flag). The source is explicit: platform model or the person's active key, never guessed. |
| B3 | Service authentication, integrity, exposure | For calls FloBrain makes to you: `Authorization: Bearer <MULTIMODAL_API_KEY>` over HTTPS or a private network (P0-1, P0-2, P1-5). No customer key or key reference is ever forwarded; the code refuses until Q13 holds and BYOK forwarding stays off by design. |
| B4 | Lifecycle states, versions, activation | States: `pending`, `active`, `rejected`, `indeterminate`, `disabled`, `expired` (Decision 20). Only FloBrain activates, disables or deletes. No silent fallback from a customer key to the platform key or to another provider. |
| B5 | Who validates a key, and how | FloBrain does it: one `GET {base}/v1/models` with a 20 second limit (`BYOK_CHECK_TIMEOUT`). 2xx is `active`; 401/403 and other 4xx are `rejected`; 429, 5xx and network errors are `indeterminate`. Your L6 probes are stricter (they prove the operation, not only the key); we will reuse them if you expose a validation call later, but nothing waits on it. |
| B6 | Route, transport, error mapping, compatibility | What FloBrain V2 needs from you is P1-3 (`POST /v1/chat/completions`, OpenAI shape) with the error table in P0-3. `/process` stays as it is for V1. Your internal codes (L2) can map onto that table. |
| B7 | Limits, spooling, telemetry, retention | Your L5 limits are fine for FloBrain (text 64 KB, audio 10 MB, 90 s per call, no retries). Keep no content and no keys in logs (P1-6). FloBrain sends no customer key, memory, documents or other people's messages (section 6). |

**One thing to fix on your side:** your 2 Oct meeting notes say part of the multimodal deploy pipeline was set up with credentials that belong to the FloBrain backend. Please give the multimodal service its own IAM role and secrets (see 4.4), and tell DevOps which FloBrain credentials were used so they can be rotated.

## 11. Status log

| Date | What changed |
|---|---|
| 2026-10-20 | First version, from `main` at `1d875b8` and a read-only AWS audit. |
| 2026-10-20 | Phase 7i: knowledge ask is direct-only by design and test. Nothing new is sent to the multimodal service. |
| 2026-10-20 | Phase 7j: live translation is direct-only. Nothing new is sent to the multimodal service. |
| 2026-10-20 | Phase 7k: BYOK keys go only to allowlisted HTTPS providers through `direct`. Q13 stays a gate for ever forwarding a key to you. |
| 2026-10-20 | Phases 8 and 9 built locally (buddies, approved actions, Content Studio). All AI goes through `direct`; nothing new is sent to the multimodal service. |
| 2026-10-20 | Phases 14 and 17 built locally. The public API, MCP, webhooks, SSO and billing never call the multimodal service. "Private only" orgs and the sovereign package refuse it by design. Nothing new is sent to you; the asks in section 4 are unchanged. |
| 2026-10-20 | **Final for handoff.** V2 code complete through Phase 17 (local, not deployed). The asks in section 4 and the rollout in section 5 are unchanged. |
| 2026-10-21 | Meetings built with FloBrain's own Whisper server, so P1-4 is now optional for FloBrain. Pulse failover never uses the multimodal service. P0, P1-1 to P1-3, P1-5 and P1-6 are unchanged and still needed. |
| 2026-10-21 | Section 10 added: FloBrain's answers to B1 to B7 from your provider-integration plan (Notion, rev 2.1). FloBrain keeps customer keys and calls providers itself, so your T5 is not needed for FloBrain. New ask: separate the multimodal deploy pipeline from FloBrain backend credentials. Sections 4 to 7 unchanged. **Send this version.** |
