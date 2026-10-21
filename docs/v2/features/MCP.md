# MCP hub (growth round M1)

FloBrain becomes a remote MCP server that Claude, ChatGPT and other MCP clients connect to with
OAuth, and a governed hub for the outside MCP servers buddies use. Off by default (flag `mcp_hub`).

## What it does

- **Remote MCP server with OAuth.** `POST /api/mcp` (streamable HTTP, JSON-RPC 2.0, protocol
  `2025-06-18`) now accepts OAuth 2.1 access tokens next to personal access tokens. A client finds
  everything from a 401: `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource/api/mcp"`.
- **More tools**, each running as the person who connected the app (same visibility, permissions
  and flags as in FloBrain, checked on every call):

  | Tool | Scope | Needs | What it returns |
  |---|---|---|---|
  | `tasks_list`, `rooms_list`, `time_report` | `tasks:read`, `rooms:read`, `time:read` | (existing) | as before |
  | `knowledge_search` | `knowledge:read` | `memory_search` | results plus cited snippets `[n] title: excerpt` |
  | `buddy_ask` | `buddies:read` | `buddies`, `ai.use`, a buddy you can use | one answer with citations; no tools are offered, so the buddy cannot act |
  | `data_ask` | `data:read` | `data_buddy`, `data.use`, a dataset you can see | answer, the checked SELECT, rows, chart (the `data.ask` pipeline) |
  | `approvals_list` | `approvals:read` | none | your own waiting proposals and outside agent calls (summaries, no arguments) |
  | `meetings_recent` | `meetings:read` | `meeting.view` | summaries, decisions, action items of meetings in rooms you can open; never transcripts |
  | `tasks_create`, `rooms_post_message` | `tasks:write`, `rooms:write` | `ai_actions` | an `ActionProposal` only (existing) |
  | `automation_run` | `automations:write` | `automations`, `ai_actions`, `automations.use` | an `ActionProposal` for the new `automations.run` action; the run starts only after approval |

  Hub tools appear in `tools/list` only while `mcp_hub` and their own flag are on. Every tool has MCP
  annotations: `title`, `readOnlyHint`, `idempotentHint`, `openWorldHint`, and `destructiveHint` on
  write tools (`false` for task and message proposals, `true` for `automation_run`).
- **Apps connected to FloBrain.** Each OAuth approval is a grant (client, person, org, scopes).
  Members see and disconnect their own; `mcp.manage` sees and disconnects everyone's. Disconnecting
  revokes every access and refresh token of that grant at once.
- **Governance for outside MCP servers** (the existing external agents): per tool allow or deny,
  read-only mode (only tools the server marks `readOnlyHint`), an end date, and which buddies may use
  the server. Enforced in `platform_api.external_agents` when tools are offered to a buddy, when a
  call is proposed, when a person tests a tool, and again when an approved call is sent (a call
  proposed before a rule changed fails with the rule's code and nothing is sent). A policy keeps
  applying if `mcp_hub` is later turned off.
- **Call log.** One row per MCP tool call, in (apps calling FloBrain) and out (buddies calling
  outside servers): tool, app or server, person, ok or error code, duration, and a redacted shape of
  the arguments (key names and value types and sizes, never values; keys that look secret, such as
  `password`, `token`, `api_key`, `authorization`, are shown as `[hidden]`). Kept 90 days.
- **Settings page** `/w/[org]/settings/mcp`: your MCP endpoint with copy and plain steps for Claude
  and ChatGPT, connected apps, outside server rules (switches per tool, read-only, end date, buddies),
  and the call log with filters (direction, result, tool, app or server, period).
- **Consent page** `/w/oauth/consent`: app name, where you return to, an org picker (orgs without
  the hub are shown but disabled), each scope in plain words with a checkbox, Allow and Deny.
  Signed-out people go to sign-in and come back. Works with the keyboard and right to left.

## Flags and permissions

- Flag `mcp_hub` (org and member flag, plan entitlement). Off: hub endpoints answer 501, OAuth
  access tokens answer 501 on `/api/mcp`, consent for that org answers 501, hub tools are not
  listed, no call log rows are written. PATs and the six original tools keep working as before.
- `mcp.manage` (owners and admins): outside server rules, the call log, everyone's connected apps.
- Without it, a member can open the page to see the endpoint and their own connected apps.

## Endpoints

Root level (served by `platform_api/public_urls.py`, already included at `""` in `flobrain/urls.py`,
so no shared URL change is needed):

| Method | Path | Notes |
|---|---|---|
| GET | `/.well-known/oauth-protected-resource` and `…/api/mcp` | RFC 9728 |
| GET | `/.well-known/oauth-authorization-server` | RFC 8414; issuer = API origin |
| POST | `/oauth/register` | RFC 7591 dynamic client registration |
| GET | `/oauth/authorize` | code + PKCE S256; sends the browser to the consent page |
| POST | `/oauth/token` | `authorization_code`, `refresh_token`; form or JSON |
| POST | `/oauth/revoke` | RFC 7009 |
| POST | `/api/mcp` | MCP; PAT or OAuth bearer |

Under `/api/v2/` (V2 session, JWT):

| Method | Path | Access |
|---|---|---|
| GET, POST | `mcp/consent?request=…` | signed-in person |
| GET | `orgs/{org}/mcp/overview` | member |
| GET | `orgs/{org}/mcp/clients[?all=1]` | own, or all with `mcp.manage` |
| DELETE | `orgs/{org}/mcp/clients/{grant}` | own, or any with `mcp.manage` |
| GET | `orgs/{org}/mcp/servers` | `mcp.manage` |
| PUT, PATCH | `orgs/{org}/mcp/servers/{server}/policy` | `mcp.manage`; `tool_rules`, `read_only`, `expires_at`, `buddy_ids` |
| GET | `orgs/{org}/mcp/calls?direction&ok&tool&client&user&days` | `mcp.manage`; newest 200 |

## Authorization flow

Follows the MCP authorization spec, 2025-06-18:
<https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization> (and the OAuth 2.1
draft, RFC 9728, RFC 8414, RFC 7591, RFC 8707, RFC 7009, RFC 9207 for the `iss` response parameter).

1. The client calls `/api/mcp`, gets 401 with `resource_metadata`, reads both metadata documents.
2. It registers (`/oauth/register`). Redirect URIs must be `https`, or `http` on `localhost`,
   `127.0.0.1` or `[::1]`; no fragment, no user info, at most 5. Public clients
   (`token_endpoint_auth_method: none`) get no secret; `client_secret_post` or `client_secret_basic`
   clients get a `fbs_` secret shown once and stored hashed. Rate limit: 10 per hour per IP
   (`MCP_OAUTH_REGISTER_RATE`), and at most 500 new clients per day (`MCP_OAUTH_MAX_CLIENTS_PER_DAY`).
3. `/oauth/authorize` checks the client and the exact redirect URI first (otherwise it never
   redirects to the app; it shows an error on the consent page). Then it needs `response_type=code`,
   `code_challenge_method=S256` and a valid challenge, and `resource` (when sent) must be this MCP
   endpoint (`invalid_target` otherwise). It sends the browser to
   `{FRONTEND_BASE_URL}/w/oauth/consent?request=…`, a request signed with the server secret that
   expires in 15 minutes.
4. The person picks an org (`mcp_hub` on, active member) and scopes (a subset of what the app asked
   for; `mcp` is always included). FloBrain creates or updates the grant and a code (`fbo_`, hashed,
   5 minutes, single use) and returns the app's redirect URI with `code`, `state` and `iss`.
5. `/oauth/token` exchanges the code: same client, exact redirect URI, verifier matching the S256
   challenge, `resource` (when sent) matching. Reusing a code revokes everything it issued. The
   answer is an access token (`fba_`, 1 hour, bound to the MCP endpoint) and a refresh token (`fbr_`,
   30 days). `Cache-Control: no-store`.
6. Refresh rotates: each refresh token works once. Presenting a used one revokes the whole grant
   (both tokens of every generation) and writes `mcp.oauth.refresh_reused` to the audit log. A
   refresh can narrow scopes, never add them.
7. On every MCP request the access token must be unexpired and unrevoked, issued for this endpoint
   (`resource` equals the canonical `/api/mcp` URL, so a token for another resource is refused), its
   grant active, the person still an active member, the password unchanged since the grant, and
   `mcp_hub` on. A failed membership or password check revokes the grant.

Scopes are the PAT scopes plus five new ones (`buddies:read`, `data:read`, `approvals:read`,
`meetings:read`, `automations:write`), which PATs accept too.

## Models (migration `platform_api/0003_mcp_hub`)

`OAuthClient` (`mcp_oauth_clients`), `OAuthGrant` (`mcp_oauth_grants`, the token family),
`OAuthAuthorizationCode`, `OAuthAccessToken`, `OAuthRefreshToken` (only SHA-256 hashes), 
`MCPServerPolicy` (one per external server), `MCPCallLog` (indexed by org and time).

## Security notes

- Only hashes of client secrets, codes, access and refresh tokens are stored. Tokens are never
  logged or returned by any list endpoint.
- PKCE S256 is required for every client, public or confidential. `plain` is refused.
- Redirect URIs are matched exactly, both at authorize and at the token endpoint.
- Audience binding: an access token works only on the resource it was issued for; FloBrain never
  passes a client's token on to another server (no token passthrough).
- The consent request is signed and expires; the consent POST needs the person's own session.
- Hub tools are read-only or proposal-only. `buddy_ask` offers the model no tools, and tool calls in
  its answer are ignored. Writes still go through `actions.service.check` and an approval.
- The call log never stores argument values. `log_call` never raises, so logging cannot break a call.
- Throttles: registration 10/hour, token and revoke 60/min, authorize 60/min, metadata 120/min per IP
  (settings `MCP_OAUTH_*_RATE`); the MCP endpoint keeps the PAT throttles (per token and per user).

## Demo

`demo/extras/a1_mcp.py`: "Claude (demo)" connected by the owner and one member (random tokens,
only hashes stored, so nobody can use them), 30 call log rows over the last week (in and out, a few
errors), and rules on "Partner agent (Demo)": `echo` turned off, read-only, access ends in 60 days,
only the Release notes buddy. Nothing touches the network.

## Before production

- Set `PUBLIC_API_BASE_URL` to the public API origin (for example `https://api.flobrain.ai`). The
  issuer, the resource and the metadata URLs come from it; without it they follow the request host,
  which behind a proxy may be wrong. `FRONTEND_BASE_URL` must point at the web app (consent page).
- The API host must serve `/.well-known/…` and `/oauth/…` at its root (they are in
  `platform_api/public_urls.py`). Check the load balancer or CDN forwards those paths.
- Browser-based MCP clients (for example the MCP Inspector) call the metadata, registration and
  token endpoints from a browser and need CORS on those paths. Claude and ChatGPT connect from their
  servers and do not.
- Schedule `python manage.py purge_mcp_logs` daily (the log also purges itself at most hourly when
  rows are written).
- `buddies/chat.py` should pass the buddy to `external_agents.offered_tools(user, org, buddy=buddy)`
  so a server limited to some buddies is not even offered to others. Until then such a call is
  refused when proposed (`buddy_not_allowed`).
- Claude and ChatGPT menu names in the setup steps can change; check them before a launch.

## Known limits

- One MCP resource per installation (`/api/mcp`). No per-org endpoint.
- No `GET` SSE stream on `/api/mcp` (the server answers each POST with JSON), no sessions.
- Unused registered clients are not cleaned up yet; the daily cap bounds them.
- Client names come from registration and are not verified; the consent page says so ("Not reviewed
  by FloBrain") and shows the host the person returns to.
- The call log shows the newest 200 rows per query; filters narrow it.
