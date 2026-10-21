# Review: completion round (2026-10-21)

An independent reviewer (who did not write the code) read the whole uncommitted batch: meetings demo, SAML and the demo identity provider, insights, external agents, rooms, tasks and time, docs, people and access, AI admin, platform, Content Studio and the Helm chart. Findings and what was done:

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | A team lead could add anyone to their own team, then pause or terminate them (and see their team data) | A lead (without `team.manage`) adds only people who are on no team yet; moving someone between teams is for admins. Test: `test_lead_cannot_pull_someone_from_another_team_to_gain_power_over_them` |
| 2 | High | Leads saw AI usage per person and could export every call; "keep my insights personal" was ignored in usage and Pulse cost | Leads see their team members combined, never per person, and can't export. People who keep insights personal have no row of their own in usage, the CSV or Pulse cost (a "People who keep their insights personal" bucket). Tests in `telemetry/test_usage_summary.py` |
| 3 | Medium | Time entries showed private room names, task titles, project and tags to teammates, even with sharing off | Names of rooms and tasks the viewer can't open are left out (reports show "Private"); with sharing off only times and the category remain. Test: `test_private_room_names_and_hidden_details_never_reach_teammates` |
| 4 | Medium | An outside agent's answer was stored as the buddy's own message and replayed to the model as such | New message role `external` (`brain/0006`): shown quoted, and sent to the model only as untrusted data in the user's turn. The buddy test now approves the injection and checks the next turn |
| 5 | Low | A microphone published while recording was starting was not recorded | The webhook records tracks during "starting" too. Test added in `test_calls.py` |
| 6 | Low | N+1 queries on room lists, doc lists and pending members | One query each now. Buddy share deciders run once per request (left as is) |
| 7 | Low | Uploaded test files under `backend/local_media/` were not ignored | Deleted and git-ignored |

Found during the final checks (not by the reviewer):

- `MeetingBotSession.status` was 16 characters but `waiting_admission` is 17: PostgreSQL refused it. Widened to 24 (`meetings/0008`) with a test that every status fits.
- `tasks/0002` and `marketplace/0002` mixed schema changes and data updates in one transaction; on a PostgreSQL database that already has tasks this fails ("pending trigger events"). The data steps are now their own migrations (`tasks/0003`, `marketplace/0003`, `marketplace/0004`). Proven by migrating a database built from the previous commit, with demo data, to this one.
- A context key with a space (`room tab|AI`) showed its prefix in English. Fixed with a test.
- The caption-language note promised translation that doesn't exist; it now says so.

Checked and found fine by the reviewer: SAML signature and wrapping defences, XML parsing, single-use requests, per-org audience; the demo identity provider (demo only, escaped, strict CSP, its key never serialized); local file storage (signed expiring URLs, path checks, downloads as attachments); outbound fetches (allowlists, pinned client, no redirects); the demo AI key refused outside demo mode; billing checkout owner-only and server-side; proposal edits re-validated; room AI sources only to `direct` or the member's own key; support sessions read-only; the Helm chart reads secrets only from an existing Secret.

Result after the fixes: 760 backend tests on SQLite and on PostgreSQL 16, website type check, eslint and 80 unit tests, all passing.
