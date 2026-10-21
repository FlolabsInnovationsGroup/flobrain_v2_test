# Phase 14 plan: public API, webhooks, MCP, status page

Branch `v2/phase-7-ai` continues (local, not pushed). Sources: `PLAN.md` Phase 14, spec 6.18 and 7, Decision 42, Q24 (MCP allowlist stays empty). Flag `api_access` (default off, 501).

## Rules for every step

- **Tokens, never sessions.** External access uses personal access tokens (PAT): `fbp_` + random, SHA-256 hash stored, shown once, scoped, optional expiry. Every request re-checks: token not revoked or expired, membership active, `api_access` on, the scope, and `can()` for the object. A password change or deactivation revokes the user's tokens.
- **Same rules as the app.** The public API reuses the V2 services and selectors (`visible_tasks`, `accessible_rooms`, `create_task`), so a token never sees more than its owner.
- **Writes through approvals for agents.** MCP write tools create `ActionProposal`s (Decision 33); the human approves in FloBrain.
- **Webhooks are outbound only to safe hosts.** HTTPS only; DNS resolved and private, loopback, link-local, multicast and reserved addresses rejected at save **and** at send; no redirects; HMAC-SHA256 signature with a timestamp; the secret is encrypted and shown once. Payloads carry ids and small fields only, never message bodies, and nothing from direct or group rooms.
- **Status page stays up when the API is down.** It is a static file built by a command and served from separate hosting (`INFRA_CHANGES.md`).

## 14a — Personal access tokens

`platform_api.PersonalAccessToken`. `GET/POST /api/v2/me/tokens?org=`, `DELETE /api/v2/me/tokens/{id}`. Scopes: `tasks:read`, `tasks:write`, `rooms:read`, `time:read`, `knowledge:read`, `mcp`. Authentication class for `/api/public/v1/` and `/api/mcp`. Per-token rate limit.

## 14b — Public REST API v1

`/api/public/v1/`: `me`, `tasks` (list, get, create), `rooms` (list, messages of rooms the owner can read now), `time/entries` (own). OpenAPI tagged for the developer docs page.

## 14c — Outgoing webhooks

`WebhookEndpoint` (admin, `webhooks.manage`), `WebhookDelivery` (attempts, status code, next try). Events: `task.created`, `task.completed`, `member.joined`, `meeting.ended`, `content.published`. Delivery on the 7g worker with backoff.

## 14d — MCP server

`POST /api/mcp` (JSON-RPC 2.0, streamable-HTTP style): `initialize`, `tools/list`, `tools/call`. Read tools: `tasks.list`, `rooms.list`, `knowledge.search`, `time.report`. Write tools (`tasks.create`, `rooms.post_message`) return a proposal id and "waiting for approval". Results are data for the client; nothing a client sends is treated as FloBrain instructions.

## 14e — External agents (MCP client) registry

`ExternalAgentServer` with an admin allowlist. Q24 keeps the allowlist empty, so a server can be recorded but not called until a host is allowlisted and scanned.

## 14f — Status page

`Incident` and updates (org-private, or platform-wide by `is_platform_admin`). `manage.py export_status --out status.json` writes a sanitized projection (public incidents, component states, no org data) for static hosting.
