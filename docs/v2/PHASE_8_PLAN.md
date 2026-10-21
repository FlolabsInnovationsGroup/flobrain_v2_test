# Phase 8 plan: Buddies, Buddy Builder, approved actions, reports

Branch `v2/phase-7-ai` continues (local only, not pushed). Each step is its own commit with tests on SQLite and PostgreSQL. Flags default off; a flag that is off returns 501 (E36).

Sources: `PLAN.md` Phase 8, spec 6.10, 6.15, 6.19, 7 ("Actions and reports"), 8.6, Decisions 33 and 34, E37 (live room access).

## Rules that hold in every step

- A buddy never sees more than the person using it. Retrieval reuses 7i (`accessible_rooms` at query time). A shared buddy's sources are re-checked against each **viewer**, not its creator.
- The model only **proposes**. FloBrain validates the arguments, checks `can(user, tool.perm_key, target)`, stores an `ActionProposal`, and executes only after a human approves. On approve, arguments and permissions are checked again for the **approver**. The model never executes anything.
- Everything AI goes through `direct` (platform key or the user's BYOK key). Buddies never send org content to `multimodal_legacy`.
- Every proposal, decision and execution writes `AuditEvent` and an `AITrace` span. No secret or message body in audit payloads.

## 8a — Buddies and buddy threads

| | |
|---|---|
| Models | `buddies.Buddy` (spec 6.10 fields), `buddies.BuddyPin`; `brain.Chat.buddy` nullable FK |
| Migrations | `buddies/0001_initial`, `brain/000x_chat_buddy`, `buddies/0002_seed_buddies` (data, the FloLabs org only, found by slug; no-op elsewhere; reversible) |
| Endpoints | `GET /orgs/{org}/buddies` (visible to me), `GET/PUT /orgs/{org}/buddies/pins`, `GET/POST /orgs/{org}/buddies/{buddy}/threads`, `GET /orgs/{org}/buddies/threads/{thread}`, `POST …/threads/{thread}/send` |
| Flag | `buddies` default off → 501 |
| Context | Own thread text plus, when the buddy lists sources, 7i retrieval limited to the buddy's sources **and** the user's live access. Same quoting rules as 7i |
| V1 | V1 chat views also filter `buddy IS NULL` in the same commit (spec 6.10) |
| Tests | Visibility (private/team/org), pins are per user, another user's thread 404, V1 cannot open a buddy thread, flag off 501, direct not configured 501 and no legacy call |

## 8b — Buddy Builder and sharing

| | |
|---|---|
| Endpoints | `POST/PATCH /orgs/{org}/buddies`, `POST /orgs/{org}/buddies/{id}/share` (`team` or `org`), `POST …/share/approve`, `POST …/share/reject` |
| Rules | Any member creates a **private** buddy. Team share needs that team's lead (or admin) to approve; org share needs `buddy.manage` (admin). `allowed_sources` must be rooms the creator can access now; `allowed_tools` must be tools the creator holds the permission for. Built-in buddies (no creator) are edited by `buddy.manage` only |
| Keys | `buddy.create` (member default), `buddy.manage` (admin) |
| Tests | Member cannot share org-wide; lead approves only their team; a viewer of a shared buddy does not get the creator's rooms; editing sources to a room the editor cannot see is 400 |

## 8c — Tool registry and approved actions

| | |
|---|---|
| Models | `actions.ToolDefinition` (seeded in code, synced by migration), `actions.ActionProposal` (24 h expiry) |
| Tools | `tasks.create`, `tasks.assign`, `tasks.update_status`, `rooms.post_message`, `meetings.create`, `email.draft` (stores a draft only), `reports.generate` |
| Provider | `direct` gains OpenAI-style `tools` and returns `tool_calls`. A tool call becomes a proposal, never an execution |
| Endpoints | `GET /orgs/{org}/actions?status=proposed`, `POST /orgs/{org}/actions/{id}/approve` (optional edited arguments), `POST …/reject` |
| Rules | Arguments validated against a small JSON-schema subset (types, required, enums, max lengths, UUIDs resolved inside the org). Permission checked at propose **and** at approve for the approver. Only the proposer (or someone with `action.approve` over the target) can decide. Expired proposals cannot run. Execution runs through the same services as the REST endpoints |
| Also | Fix found while planning: `POST /tasks` accepts a `project` id without checking it belongs to the org (cross-org reference). Task creation moves into one service used by the view and the tool |
| Tests | No write without an approval row; approve re-checks permission (revoked between propose and approve → 403, nothing executed); invalid arguments never stored as approved; another user's proposal 404; expired 409; audit rows without bodies |

## 8d — Daily standup and weekly report

| | |
|---|---|
| Model | `actions.AutoReport` |
| Endpoints | `GET /orgs/{org}/teams/{team}/reports?kind=`, `POST …/reports/generate` |
| Rules | Team lead or admin only. Sources: the team's tasks, time entries, blockers and team room activity for the period. The draft cites task and entry ids. Posting to the team room is a separate approved action |
| Tests | Non-lead 403, another team 404, citations point to real rows of that team only, flag off 501 |

## 8e — Skills and assignment suggestions

| | |
|---|---|
| Models | `organizations.SkillTag`, `organizations.MemberSkill` |
| Endpoints | `GET/POST/DELETE /orgs/{org}/members/{user}/skills`, `GET /orgs/{org}/tasks/{task}/suggest-assignee` |
| Rules | Deterministic score from open workload, skill overlap and past completed tasks; candidates limited to people the requester may assign (`assign_eligibility`). Suggestions only; the lead assigns |

## 8f — Scheduled and triggered agents

| | |
|---|---|
| Models | `agents.AgentSchedule`, `agents.AgentRun` |
| Rules | Runs on the 7g worker. A run uses the creator's permissions **at run time** (an inactive creator pauses the schedule). Write tools still create proposals. Every run is traced. Flag `scheduled_agents` default off; the production scheduler stays an `INFRA_CHANGES.md` item |

## Not in Phase 8

Content Studio (Phase 9), external connectors and real email sending (Phase 15), MCP (Phase 14), marketplace (Phase 17).
