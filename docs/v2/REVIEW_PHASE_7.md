# Review: Phase 7 (7h to 7k, plus the room-access fix)

Date: 2026-10-20. Built by Claude in the container. Reviewed by a separate agent that had not seen the work being written, then fixed and re-tested. Branch `v2/phase-7-ai`, local only, not pushed.

Scope: `c37bea01` (room access, E37), `d767d650` (7i knowledge ask), `e696979b` (7j translation), `7a6fe8c6` (7k BYOK). The earlier 7d–7g review is `REVIEW_7D_7G.md`.

## Findings and fixes

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Rooms | Deleting a team left its members in the rooms of projects that included the team. The cascade removes the `Project.teams` rows before the membership signal runs, so the project lookup found nothing. Those users could still read the project room and retrieve its chunks. | Medium | **Fixed**. `pre_delete`/`post_delete` on `Team` prune those project rooms. Also, `RoomMember` rows are now only a cache: team and project rooms also require **live** team/project membership (or project lead) in `accessible_rooms` and `user_can_access_room`, so a stale row from a missed signal or a race grants nothing. Tests: team delete, stale row. |
| 2 | 7i | A doc or message edited while `memory_search` was off kept its old chunks, and retrieval did not compare versions, so pre-edit text could be served after the flag came back on. The same applied while a re-index job was pending or failing. | Medium | **Fixed**. Saving a source while the flag is off deletes its chunks. Each chunk stores `source_updated_at` (`knowledge/0003`); retrieval drops a chunk whose source has changed since it was built. Tests for both paths. |
| 3 | 7j | An edit landing while a translation call was in flight cached the translation of the old body as fresh, so readers saw redacted text. | Medium | **Fixed**. The cache row stores the message version read **before** the call; any later edit makes it stale. Old stub rows (`[fr] …`) are stale by the same rule and get replaced on first read. Test simulates the edit during the call. |
| 4 | 7i | Source quoting was case-sensitive (`</SOURCE>` passed) and titles were not attribute-escaped. | Low–Medium | **Fixed**. One shared `knowledge/prompting.py`: case- and space-insensitive tag escaping, `"` escaped in titles. Used by knowledge ask and buddies. Test. |
| 5 | Rooms | Moving a `TeamMembership` to another team left the user in the old team's room. A concurrent add could re-create a just-removed row. | Low | **Fixed**. `pre_save` remembers the old team and prunes its rooms. The race is covered by the live-membership check in #1. Test. |
| 6 | 7k | A timezone-less `expires_at` caused a 500. Dropped connections (`RemoteDisconnected`, `IncompleteRead`) and non-object JSON from a provider caused a 500. Bad token counts could raise. | Low | **Fixed**. Naive dates are UTC; bad dates 400. Provider errors map to `provider_unavailable`/`provider_error`; token counts that are not non-negative integers are unknown. Still no fallback to the platform key. Tests. |

## Checked and fine (reviewer)

- pgvector SQL: table name from an integer allowlist; vector, model, ids and the subquery are bound parameters.
- Retrieval filters by org, live rooms, `docs.view` and `room.view` before ranking; hits are re-checked against the live source.
- DMs and group rooms are excluded for non-members (owners and admins too) on every list, search and retrieval path.
- BYOK: every query is org-scoped; personal keys are 404 for everyone else; only `last4` is returned; audit payloads hold scope and status only; masked `repr`; logs carry id and status only.
- Crypto: AES-GCM, random nonce, associated data binds id and org, no default key, version mismatch refused.
- SSRF: HTTPS to allowlisted hosts only, no userinfo, port, path, query or fragment; redirects off for customer keys; allowlist re-checked at use.
- No fallback: a customer-key failure never calls the platform key or the legacy host. Knowledge ask and translation use `direct` only.
- Flag-off paths return 501 before any network call.

## Not changed (noted)

- `memory_search` saves in an org with the flag off now run one small delete query per save.
- One encryption key version at a time (`TECH_DEBT.md`).
- Org keys are for owners and admins (E38, Q41).

## Proof

- SQLite: **253 tests OK** (5 skipped: Postgres-only tests).
- PostgreSQL 16 + pgvector (container): **253 tests OK**, including the pgvector ask tests.
- `makemigrations --check`: no changes. Re-run both suites on the Windows Postgres 15 before merging.
