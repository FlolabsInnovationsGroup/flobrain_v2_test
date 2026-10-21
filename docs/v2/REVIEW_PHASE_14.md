# Review: Phase 14 (public API, webhooks, MCP, status page)

Date: 2026-10-20. Reviewed by a separate agent that had not seen the work being written (`git show e8078896`), then fixed and re-tested. Branch `v2/phase-7-ai`, local only, not pushed.

No auth bypass, cross-org access or SSRF bypass was found.

## Findings and fixes

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | The MCP `rooms_post_message` write tool was gated on `rooms:read`, so a "read-only" token could create approvable message proposals. | Medium | **Fixed**. New `rooms:write` scope; the tool needs it. |
| 2 | Webhook sends had per-operation timeouts only: a receiver trickling bytes could hold the shared worker for hours; DNS had no timeout; in eager mode the send ran inside the saving request. | Medium | **Fixed**. 15 s wall-clock deadline that closes the connection, 5 s DNS timeout, and deliveries are queued only after the transaction commits. |
| 3 | The "no IP literals" rule never fired (the error was swallowed). | Low | **Fixed**. |
| 4 | Malformed URLs (bad port, 64+ character labels) caused 500s and were retried at send time. | Low | **Fixed**. 400 at save; permanent failure at send. |
| 5 | Bad token-create input (non-UUID org, non-string scopes) and bad public task bodies (array body, non-string title) caused 500s. | Low | **Fixed**. 4xx; `create_task` also refuses non-text input. |
| 6 | Deactivation revoked a token only if it was used while inactive; reactivation revived unused tokens. | Low | **Fixed**. A membership that stops being active revokes that user's tokens for the org at once. |
| 7 | MCP `knowledge_search` skipped the platform budget check. | Low | **Fixed**. |
| 8 | A delivery could be sent twice (queued job and retry tick). | Low | **Fixed**. Claimed with a conditional update (`sending`), stale claims requeued after 5 minutes. |
| 9 | No cap on webhook endpoints per org; the token throttle was per token only. | Low | **Fixed**. 20 endpoints per org; an extra per-user throttle (`PUBLIC_API_USER_RATE`, 300/min) across all tokens. |
| 10 | `member.joined` fired for pending invites (webhooks and agents); `content.published` sent the URL of private posts; `fec0::/10` passed the guard; incident updates were unbounded. | Info | **Fixed**. Active members only; URL only for public posts; site-local refused; last 100 updates kept. |

Noted, not changed: `task.created/completed` payloads go to every endpoint of the org (ids only); by default only owners and admins hold `webhooks.manage` and they see all teams.

## Proof

- SQLite and PostgreSQL 16: **381 tests OK**. `makemigrations --check`: no changes.
