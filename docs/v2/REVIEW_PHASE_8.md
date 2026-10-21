# Review: Phase 8 (buddies, Buddy Builder, actions, reports, skills, agents)

Date: 2026-10-20. Built by Claude in the container. Reviewed by a separate agent that had not seen the work being written (`git diff fd055f56..63fba5dd`), then fixed and re-tested. Branch `v2/phase-7-ai`, local only, not pushed.

No critical or high findings: the approval gate, org and user isolation and viewer-scoped buddy retrieval held. Fourteen medium and low findings, all fixed.

## Findings and fixes

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | 8d | Team reports printed member emails (leads lack `org.members.view_contact`), and posting put them in the team room. | Medium | **Fixed**. Usernames only. |
| 2 | 8d | Reports counted a member's hours on other teams' tasks and cited those entry ids. | Medium | **Fixed**. Only time on this team's tasks. |
| 3 | 8f | `task.overdue` fired for tasks the creator cannot see (ids landed in their thread); any member could create past-due tasks to spend others' budget; with more than 50 overdue tasks the rest never fired. `meeting.ended` fired for meetings in rooms the creator cannot read. | Medium | **Fixed**. Overdue tasks are filtered by the creator's `visible_tasks`, oldest first, already-handled ones skipped, 20 per tick. Meeting events check the creator's room access. New cap `AGENT_MAX_RUNS_PER_HOUR` (12) per schedule. |
| 4 | 8c | `tasks.assign` proposal summaries showed the assignee's email. | Low–Medium | **Fixed**. Username. |
| 5 | 8c | Turning a tool off did not stop proposals already pending. | Low–Medium | **Fixed**. `check()` refuses a disabled tool; approve returns 501 and nothing runs. |
| 6 | 8c | An impossible date in edited arguments (`2026-02-30`) caused a 500. | Low | **Fixed**. 400. |
| 7 | 8c | `create_task` let a member file tasks into projects they are not part of (`task.write` is team-scoped). | Low | **Fixed**. `can_use_project`: admin, project lead, direct member or member of one of its teams; otherwise 404, for REST and the tool. |
| 8 | 8f | The 15-minute floor missed gaps across midnight; a never-firing cron cost about 0.5 s of CPU per request. | Low | **Fixed**. The floor is checked on times of day with the midnight wrap; `next_after` skips whole days and hours. |
| 9 | 8f | "Run now" had no AI throttle. | Low | **Fixed**. AI send throttle plus the per-schedule hourly cap (429). |
| 10 | 8c/8d | Proposals, denied approvals and report generate/post were not audited. | Low | **Fixed**. `action.proposed`, `action.denied`, `report.generate`, `report.post`. |
| 11 | 8b | Editing preset prompts of a shared buddy did not re-open approval; an approver could approve a version edited after they looked. | Low | **Fixed**. Presets re-open approval. Approve must send the `hash` shown in the share request; a changed buddy returns 409 with the new hash. |
| 12 | 8b | Share requests showed reviewers the creator's room ids, including private ones. | Low | **Fixed**. Reviewers see rooms they can read plus a `hidden_rooms` count. |
| 13 | 8c | `tasks.create` proposals for a team the user cannot write were stored and failed later. | Low | **Fixed**. Checked at propose. |
| 14 | 8e | Skills could be read and added for inactive memberships; a race could create duplicate case-variants and then 500. | Low | **Fixed**. Active members only; lookup by `iexact` then create with an integrity retry. |

## Checked and fine (reviewer)

- Buddy retrieval always applies the viewer's live rooms, narrowed by the buddy's sources; saved rooms must be readable by the editor.
- Builder fields (`system_prompt`, `allowed_sources`) never reach non-editors.
- Buddy tools: only tools the creator holds, and re-filtered for each viewer.
- Strict schemas; target re-check for the approver in `execute()`; row lock plus status check runs once; expired refused; proposer-only (others 404); lost permission rolls back.
- All lookups org-scoped; cross-org ids rejected.
- All buddy and agent AI goes through `DirectProvider`; BYOK never falls back.
- V1 chat excludes buddy threads.
- No IDOR on pins, threads, schedules, runs, reports, skills or suggestions.
- Agents run as the creator at run time and pause on loss of access; writes stay proposals.
- Signals are savepoint-wrapped.

## Proof

- SQLite and PostgreSQL 16: all Phase 0–8 tests pass (the only error is the unwired Phase 9 WIP module, not part of this commit).
- `makemigrations --check`: no changes.
