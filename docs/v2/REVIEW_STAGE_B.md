# Stage B review — Phases 4, 5, 6

Date: 2026-10-20. Branch: `v2/phase-0-foundation` (local only). Nothing was pushed.

This is a review packet, not a changelog. It names the tests that exist, the endpoints and screens that shipped, and where Stage B differs from `PLAN.md` / the spec. Mission Control and settings/access were finished immediately before Phase 4 and are included because they were still shells at the quality pass.

The body below is the original review. Dispositions were added after the fixes. Nothing was pushed.

## Disposition (2026-10-20)

Commits, local only: `857f337` security, `6c25f07` stubs, `02aef5f` spec gaps, `4e0a465` Playwright. Backend suite after these: **103** tests on SQLite and on Postgres 15 port 5433 (was 95). Playwright: 3 passed (sign-in skeleton, member workspace smoke, owner workspace switch).

| Finding | Status |
|---|---|
| Every Phase 4–6 key allowed and denied, plus outsider | **Fixed** (`857f337`). Matrix and `can()` tests kept. |
| 403 for module denial, 404 outside room/team scope | **Fixed** (`857f337`). |
| Messages: other-org and inactive GET | **Fixed.** `test_docs_inactive_and_messages_other_org_denied`. |
| Announcements: other team, other org, inactive, foreign pin/unpin | **Fixed.** `test_announcements_isolated_and_denied` (404 / 403). |
| Recordings and transcripts: other team, other org, inactive | **Fixed.** `test_recordings_and_transcripts_isolated`. |
| Docs GET for an inactive member | **Fixed.** Same inactive test as messages. |
| Files not room-scoped; any `docs.write` member could complete a guessed id | **Fixed.** `StoredFile.room`, presign requires a room, complete is creator or owner/admin else 404. `test_files_complete_denied_outside_creator_and_org`. |
| File presign against another org | **Fixed.** Same test, 403. |
| Room members GET, message PATCH/DELETE without a dedicated denial | **Fixed.** `test_room_members_and_message_edit_denied`. |
| Input validation (tool URL, filename, empty/oversized message) | **Fixed.** Non-http(s) tool URLs rejected. Path characters in filenames rejected. |
| Secrets or credential values in `/me` or logs | **Fixed.** `test_me_omits_secrets`. Responses stay on the existing public fields. |
| Realtime ticket for a non-member | **Fixed.** Active membership required; outsider denied before the flag check. |
| Translation stub `[lang] {body}` shown as if it were a translation | **Fixed.** `translate_to` returns **501**. Toggle removed from chat. |
| Transcribe/summarize local stub text | **Fixed.** Both return **501**. Transcript GET after that is 404 until a real transcript exists. |
| Join URL `https://meet.local/{id}` | **Fixed.** No stub URL is returned. Real provider is **moved** (Q2). |
| `voice_video` default on | **Fixed.** Default is off. |
| Realtime ticket when the flag is on but Channels is not built | **Fixed.** **501** with a clear message. Flag still defaults off (503 while off). |
| Impact score placeholder | **Fixed.** API returns `null`; cockpit shows **Not configured**. |
| `ensure_project_room` and project membership sync | **Fixed** (`02aef5f`). Seed creates team and project rooms. |
| `useRoomMessages` unused; chat loaded one page | **Fixed.** Chat uses the hook and follows cursor pages. |
| Postgres full text | **Fixed** on Postgres (`SearchVector`). SQLite keeps `icontains`. |
| Announcement list on the cockpit | **Fixed.** Cockpit reads announcements. |
| Room tabs Tasks and Calendar | **Fixed.** Links to the existing tasks and calendar pages. |
| `rel="noopener noreferrer"` on tool links | **Fixed** (already set; kept). |
| Playwright smokes: sign in, org switch, rooms, tasks, Flo Chronos, permission denial | **Fixed** (`4e0a465`). 3 passed locally against Django on 8000 and Next on 3000. |
| `public/fonts/fa-solid-600.eot` missing from the working tree | **Fixed.** Restored from HEAD (32,540 bytes). `git diff --diff-filter=D origin/main` lists no deleted files, so no other asset was removed on this branch. |
| Live translation via `brain/llm` and usage events | **Moved** to Phase 7 in `PLAN.md`. |
| Room AI chat tab | **Moved** to Phase 7. |
| Real voice/video, On Call, LIVE badge, call window, screen share, meeting-started notification, recording notice, focused video viewer | **Moved.** Q2 / later Phase 5. |
| Real transcription and summarize workers | **Moved.** Q14 / Q17. |
| Django Channels consumer and Redis | **Moved.** Q7 / infra. |
| S3 presigned uploads | **Moved.** No AWS until infra approval. Local upload paths stay. |
| Rich-text editor, autosave debounce, revision browser, tool reorder | **Moved.** Phase 6 polish in `PLAN.md`. |
| Avatars, active-member strip, message-search UI, timer `room` foreign key | **Moved.** Phase 4 polish in `PLAN.md`. |
| Report, Team, and Recordings room tabs | **Moved.** Phase 4/5 polish in `PLAN.md`. Tasks and Calendar already link to existing pages; report, team, and recordings do not have room-filtered screens yet. |
| Highlight clips | **Moved** to Phase 9. |
| App package `docs_app` instead of `docs` | **Won't fix.** `docs` is not a safe Python package name here. `AppConfig.label = "docs"`, so the app label stays `docs`. |
| Migration file `meetings/0002_initial` instead of `0002_transcript_summary` | **Won't fix.** The migration is already applied on SQLite and Postgres. Renaming an applied migration would rewrite history. Models match the spec. |
| Open question: file scope | **Fixed** by room scope above. |
| Open question: project rooms | **Fixed** by `ensure_project_room`. |
| Open question: keep the translation stub | **Moved** with live translation to Phase 7. |
| Open question: recording/transcript isolation tests | **Fixed** by the named 404 tests. |
| Open question: announcement isolation tests | **Fixed** by the named tests. |
| Open question: chat cursor pagination | **Fixed.** The screen follows `next`. |

---

## 1. Permission keys added in Phases 4–6

Catalog: `organizations/permissions/registry.py` (`PHASE_4_TO_6_API_KEYS`).

Member defaults that include the key: member is the **allowed** user (200/201). Keys not in member defaults: owner is allowed; member is an extra **denied** path (403). Every key also denies an org outsider (401/403).

The matrix test is one method that loops all ten keys:

`organizations.tests.test_phase4_6_quality.Phase46PermissionApiTests.test_every_phase_4_to_6_key_allowed_and_denied`

Engine-level allowed/denied (no HTTP):

`Phase46PermissionApiTests.test_can_matches_role_defaults_for_every_key`  
(owner True, member matches defaults, outsider False, inactive False)

| Key | Matrix | Member default? | Allowed probe | Denied probe | Named tests |
|---|---|---|---|---|---|
| `room.view` | team | yes | `GET /orgs/{org}/rooms` as member → 200 | outsider → 403 | **Allowed + denied:** `Phase46PermissionApiTests.test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed:** `RoomApiTests.test_member_posts_and_cannot_see_other_team_room` (list own rooms). **Also denied:** `RoomApiTests.test_other_org_and_inactive_denied` |
| `room.manage` | org | no | `POST /orgs/{org}/rooms` `{name}` as owner → 201 | outsider 403; member 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also denied:** `RoomApiTests.test_member_cannot_manage_rooms_or_pin` |
| `announcement.manage` | org | no | `POST /orgs/{org}/announcements` as owner → 201 | outsider 403; member 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed (owner) + denied (member):** `RoomApiTests.test_member_cannot_manage_rooms_or_pin` |
| `notification.view` | org | yes | `GET /orgs/{org}/notifications` as member → 200 | outsider → 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed:** `NotificationApiTests.test_list_own_and_mark_read`. **Also denied:** `NotificationApiTests.test_other_org_denied` |
| `meeting.view` | team | yes | `GET /orgs/{org}/rooms/{room}/meetings` as room member → 200 | outsider → 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed (member_a) + denied (inactive):** `MeetingApiTests.test_owner_creates_and_member_isolated` |
| `meeting.manage` | team | no | `POST /orgs/{org}/rooms/{room}/meetings` as owner → 201 | outsider 403; member 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed:** `MeetingApiTests.test_owner_creates_and_member_isolated`. **Also denied:** `MeetingApiTests.test_member_cannot_manage_and_confirm_required` |
| `docs.view` | team | yes | `GET /orgs/{org}/rooms/{room}/docs` as room member → 200 | outsider → 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed:** `DocsApiTests.test_write_conflict_and_isolation` (create then read). |
| `docs.write` | team | yes | `POST /orgs/{org}/rooms/{room}/docs` as room member → 201 | outsider → 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed:** `DocsApiTests.test_write_conflict_and_isolation`, `DocsApiTests.test_files_stay_local_and_inactive_denied` (presign uses `docs.write`) |
| `tools.manage` | org | no | `POST /orgs/{org}/tools` as owner → 201 | outsider 403; member 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed (owner PATCH/DELETE) + denied (member POST/DELETE):** `ToolsApiTests.test_member_lists_defaults_owner_manages` |
| `search.use` | org | yes | `GET /orgs/{org}/search?q=hello` as member → 200 | outsider → 403 | **Allowed + denied:** `test_every_phase_4_to_6_key_allowed_and_denied`. **Also allowed (filtered):** `Phase46PermissionApiTests.test_search_hides_other_team_content` |

`GET /orgs/{org}/tools` is gated by `org.view` (Phase 0–3), not `tools.manage`. Members may list tools; they may not create/patch/delete.

`chat.use` (Phase 0–3) still gates posting and listing messages. Empty body → 400: `RoomApiTests.test_member_posts_and_cannot_see_other_team_room`.

---

## 2. Isolation tests

Convention from Stages A/B: **403** = not an active member of that org (or missing org-level perm); **404** = in the org but outside object scope (other team / not a room member).

### Coverage matrix

| Surface | Other team / non-member of room | Other org | Inactive member |
|---|---|---|---|
| Rooms list/detail | **Yes** — `RoomApiTests.test_member_posts_and_cannot_see_other_team_room`; `Phase46PermissionApiTests.test_isolation_other_team_other_org_inactive` (`GET .../rooms/{room_b}` 404; list omits it) | **Yes** — `RoomApiTests.test_other_org_and_inactive_denied`; `test_isolation_other_team_other_org_inactive` | **Yes** — both tests above (`GET /rooms` 403) |
| Messages | **Yes** — `test_member_posts_and_cannot_see_other_team_room`; `test_isolation_other_team_other_org_inactive` (`GET .../messages` 404) | Not a dedicated `GET other-org/rooms/{id}/messages`. Other-org `GET /rooms` is 403 (`IsActiveOrgMember`). | Not a dedicated messages GET. Inactive `GET /rooms` is 403. |
| Announcements | **Partial.** Member POST pin is 403 (`test_member_cannot_manage_rooms_or_pin`) — that is missing `announcement.manage`, not room isolation. There is **no** test that a Team B member `GET`s announcements pinned in Team A’s room, or `POST`s a pin into a room they are not in. | **No named test** on `/announcements`. | **No named test** on `/announcements`. |
| Meetings | **Yes** — `MeetingApiTests.test_owner_creates_and_member_isolated` (member_b GET room_a meetings 404); `test_isolation_other_team_other_org_inactive` | **Yes** — `MeetingApiTests.test_other_org_denied` (403 or 404) | **Yes** — `test_owner_creates_and_member_isolated` (403) |
| Recordings | **No named test.** List uses `_room_or_404`, so a non-member would 404, but `GET .../recordings` is not asserted. | **No named test.** | **No named test.** |
| Transcripts | **No named test.** `GET .../transcript` checks `user_can_access_room` then 404, but no isolation assertion. Transcribe/summarize in `test_member_cannot_manage_and_confirm_required` run as **owner**. | **No named test.** | **No named test.** |
| Docs | **Yes** — `DocsApiTests.test_write_conflict_and_isolation` (member_b GET doc and room_a docs 404; docs search hides other-team doc); `test_isolation_other_team_other_org_inactive` | **Yes** — `DocsApiTests.test_files_stay_local_and_inactive_denied` (`GET other-org/docs/search` 403) | **No named test** on docs GET. Inactive is covered for files (below) and for rooms/search in the Phase 4–6 isolation test. |
| Files | **Not room-scoped.** Presign/complete are org-level (`docs.write`). No test that a Team B member is blocked from completing Team A’s file id. | **No named test** on `/files/presign` against another org. | **Yes** — `DocsApiTests.test_files_stay_local_and_inactive_denied` (presign 403) |
| Search | **Yes** — `Phase46PermissionApiTests.test_search_hides_other_team_content` (other-team room + doc titles absent) | **Yes** — `test_isolation_other_team_other_org_inactive` (`GET other-org/search` 403) | **Yes** — same test (`GET /search` 403) |

### Other isolation that did ship

- Inactive cannot receive a **new DM room**: `RoomApiTests.test_inactive_cannot_receive_new_dm_room` (404).
- Tools other org + inactive: `ToolsApiTests.test_other_org_and_inactive_denied`.
- Notifications other org + outsider: `NotificationApiTests.test_other_org_denied`. Own-only list: `test_list_own_and_mark_read`.
- Owners/admins bypass room membership (`rooms.services.user_can_access_room`) so owner probes against `room_a` succeed without a `RoomMember` row.

---

## 3. New endpoints and screens

All under `/api/v2/`.

### Phase 4

| Method | Path |
|---|---|
| GET, POST | `orgs/{org}/rooms` |
| GET | `orgs/{org}/rooms/search` |
| GET, PATCH | `orgs/{org}/rooms/{room}` |
| GET | `orgs/{org}/rooms/{room}/members` |
| GET, POST | `orgs/{org}/rooms/{room}/messages` |
| PATCH, DELETE | `orgs/{org}/rooms/{room}/messages/{id}` |
| GET, POST | `orgs/{org}/announcements` |
| POST | `orgs/{org}/announcements/{id}/unpin` |
| POST | `realtime/ticket` |
| GET | `orgs/{org}/notifications` |
| POST | `orgs/{org}/notifications/read` |

### Phase 5

| Method | Path |
|---|---|
| GET, POST | `orgs/{org}/rooms/{room}/meetings` |
| GET | `orgs/{org}/rooms/{room}/recordings` |
| POST | `orgs/{org}/recordings/{id}/transcribe` |
| GET | `orgs/{org}/recordings/{id}/transcript` |
| POST | `orgs/{org}/meetings/{id}/summarize` |
| GET | `orgs/{org}/meetings/{id}/summary` |
| POST | `orgs/{org}/meetings/{id}/action-items/{item_id}/to-task` |

### Phase 6

| Method | Path |
|---|---|
| GET, POST | `orgs/{org}/tools` |
| PATCH, DELETE | `orgs/{org}/tools/{id}` |
| GET, POST | `orgs/{org}/rooms/{room}/docs` |
| GET, PATCH | `orgs/{org}/docs/{doc}` |
| GET | `orgs/{org}/docs/search` |
| POST | `orgs/{org}/files/presign` |
| POST | `orgs/{org}/files/{id}/complete` |
| GET | `orgs/{org}/search` |

Endpoints with **no dedicated test** (only reachable if you hit them by hand, or indirectly): room members GET, message PATCH/DELETE, announcement GET/unpin, recordings GET, transcript GET (except as a side effect of owner transcribe in the confirm-to-task test), tools GET is tested, docs GET is tested via isolation.

### Screens

Shared states via `ScreenBody` + `screenStateFromHttp`: **loading**, **empty**, **ready**, **no-access** (401/403/404), **error** (0 or ≥400 otherwise). Vitest covers screen **logic**, not the React trees.

| Screen | Path / placement | States | Vitest |
|---|---|---|---|
| Mission Control | `/w/[org]/mission-control` | all four + ready; empty when no activity | `missionControl.test.ts` |
| Access | `/w/[org]/settings/access` | all four + ready; empty when no pending requests/grants | `access.test.ts` |
| Rooms sidebar | workspace layout | all four + ready; empty “No rooms yet” | `rooms.test.ts` |
| Chat | `/w/[org]/rooms/[roomId]` | all four + ready; empty “No messages yet”; translation toggle | `chat.test.ts` |
| Meetings | `/w/[org]/rooms/[roomId]/meetings` | all four + ready; empty “No meetings yet” | `meetings.test.ts` |
| Docs | `/w/[org]/rooms/[roomId]/docs` | all four + ready; empty “No documents yet”; 409 → error | `docs.test.ts` |
| Notifications | `/w/[org]/notifications` | all four + ready; empty “No notifications” | `notifications.test.ts` |
| Search | `/w/[org]/search` | all four + ready; empty “No results” | `search.test.ts` |
| Tools page | `/w/[org]/tools` | all four + ready; empty “No tools yet” | `tools.test.ts` |
| Tools rail | layout right aside | same four + ready | `tools.test.ts` (shared logic) |

Room tabs on chat/meetings/docs: Chat, Meetings, Docs only (not Tasks / Report / Calendar / Team / AI Chat).

---

## 4. Test results

Recorded 2026-10-20 on this machine. Not re-run for this document.

### Django checks (after Phase 4–6 migrations)

```
manage.py check
System check identified no issues (0 silenced).

manage.py makemigrations --check --dry-run
No changes detected
```

(The same two commands were also clean **before** Phase 4, when the new apps had no `migrations` packages yet.)

### Backend suite

| Engine | Command | Result |
|---|---|---|
| SQLite (`DB_ENGINE=sqlite`) | `manage.py test --noinput` | **Ran 95 tests in 279.398s OK** |
| PostgreSQL 15 on **5433** (`flo_user` / `flobrain_db`, data dir `D:\pgsql15-data`) | same | **Ran 95 tests in 475.502s OK** |

Same count on both engines. Quality pass was 75; Stage B added 20.

Focused Stage B subset (rooms, notifications, meetings, docs_app, integrations, `test_phase4_6_quality`, `test_phase0_3_quality`): 29 OK.

Docker CLI is not installed. Postgres is the user-owned cluster, not Compose.

### Frontend V2 slice

Paths: `src/lib/axios.test.ts`, `src/i18n`, `src/lib/v2` (and the quality-pass set also included `src/components/v2`, `src/app/w`).

**27 passed** (19 files). Was 19 after the Phase 0–3 quality pass.

Run with `vitest --environment node` after local `node_modules` was missing `jsdom`/`css-tree`. Full website Vitest (271 / 41 / 312, same 41 failures as `origin/main`) was **not** re-run this Stage B.

Screens were not click-tested in a browser (no authenticated local workspace session).

---

## 5. Diffs from the spec / `PLAN.md`, skipped work, defaults, open questions

### Differently from PLAN.md / spec

| PLAN / spec | What shipped |
|---|---|
| Translation via `brain/llm` V2 entry, writing `UsageEvent` / `AITrace` | Stub cache: `[{lang}] {body}` in `rooms/translation.py`. Original row is never mutated (tested). No LLM, no telemetry on translate. |
| Signals sync **team and project** membership to rooms | **Team only** (`rooms/signals.py` on `TeamMembership`). No `ensure_project_room`. Unique project-room constraint exists on the model but is unused. |
| `realtime/` Channels consumer + ticket behind flag | Ticket only. `POST /api/v2/realtime/ticket` → **503** unless `realtime` is on (`RoomApiTests.test_realtime_ticket_unavailable`). No consumer, no Redis. |
| `useRoomMessages` polling hook | Hook file exists (`src/lib/v2/useRoomMessages.ts`). `ChatScreen` polls with `setInterval` + `ROOM_POLL_MS` directly and does not call the hook. |
| Cursor pagination in the chat UI | API uses `V2CursorPagination`. The screen loads one page and merges; it does not follow `next`. |
| Docs app named `docs/` | Package is `docs_app` with `label = "docs"` so the table/app label still reads `docs`. |
| `meetings/0002_transcript_summary` | `meetings/0001_initial` + `0002_initial` (FK split). Same models, different migration names. |
| Presigned **S3** uploads | Local only: `upload_url` `/local-uploads/{id}`, complete URL `/media/local/...`. Asserted in `DocsApiTests.test_files_stay_local_and_inactive_denied`. |
| Global search: Postgres full text | `icontains` on title/body/content, not `SearchVector` / `tsvector`. |
| Join URL from Q2 provider | Stub `https://meet.local/{id}` (`meetings/providers.py`). |
| Transcription Q14 / jobs Q17 | Eager local stubs: `"Local transcript stub."` / `"Local summary stub."` via `jobs.enqueue` (eager in tests). |
| Files as room/knowledge objects | `StoredFile` is **org-scoped**, not tied to a room. Any active member with `docs.write` can presign. |
| Decision 13 timestamps | Implemented in `formatRoomTimestamp` (just now / X min ago / X hours ago / `Intl`). |
| Decision 38 live translation | Per-reader, cached per message+language, “Translated” label, toggle. Language hardcoded to `ar` in the chat screen. |
| Human confirm for action-item → task | Required: missing `confirm` → 400; `confirm: true` → 201 (`MeetingApiTests.test_member_cannot_manage_and_confirm_required`). |

### Skipped (spec Phase 4–6 scope, not built)

Phase 4: avatars, active-member strip, announcement in cockpit, timer linked to room, room tabs for tasks/report/calendar/team, Channels, message search UI beyond room name filter, project auto-rooms.

Phase 5: real voice/video SDK, On Call presence, LIVE badge, min/max call window, screen share, “meeting started” notification, recording notice, focused video viewer, searchable transcripts UI, highlight clips (Phase 9).

Phase 6: rich-text editor, autosave debounce, revision browser, tool reorder UI, `rel="noopener noreferrer"` is set on tool links, Postgres FTS, S3.

Room AI chat is Phase 7 by spec — not started.

### Safe defaults used

- **Q7 Redis / realtime:** off. Polling 5s. Ticket 503.
- **Q2 provider:** local stub URL, no Zoom/LiveKit/Daily.
- **Q14 transcription:** local stub text, not multimodal ASR.
- **Q17 job queue:** `JOBS_EAGER` (true in DEBUG/tests); no Celery/SQS/Redis.
- **Q17 / files:** no AWS, no S3, no production bucket.
- Feature flag `voice_video` defaults **on** (`effective_flag(..., default=True)`); `realtime` defaults **off**.
- Empty chat messages rejected (400).
- Tool URLs validated (`http`/`https` only).
- Document stale `version` → 409; last 50 revisions kept (`FLOBRAIN_V2.DOCUMENT_REVISIONS_KEPT`).

### New open questions (not yet in `OPEN_QUESTIONS.md`)

1. **File scope.** Should `StoredFile` be room- or org-scoped? Today any `docs.write` member can complete any file id in the org if they guess the UUID.
2. **Project rooms.** Ship `ensure_project_room` + `ProjectMembership` signal in a follow-up, or keep team rooms only until someone asks?
3. **Translation.** Keep the `[lang]` stub until Phase 7’s multimodal adapter, or wire `brain/llm` now with usage events?
4. **Recordings/transcripts isolation tests.** Add named 404s for non-members before Phase 7, or accept the `_room_or_404` code path as enough?
5. **Announcement list isolation.** GET is filtered by rooms the user belongs to; there is no test. Pin/unpin in a foreign room is untested.
6. **Chat pagination.** Should the UI follow cursor `next`, or is a polling snapshot of the latest page enough until realtime?

Existing unanswered questions that still block *production* or later phases: Q11, Q12, Q27–Q30 (prod rollout); Q7, Q2, Q14, Q17 (this stage used defaults); Q1, Q13, Q26, Q35 (Phase 7).

---

## 6. `git log --oneline -15`

```
8e8a8c6 docs(v2): fill Stage B commit hashes in PROGRESS
5e74614 docs(v2): record Stage B test counts and stop before Phase 7
e7da479 feat(v2): add Stage B rooms, meetings, docs, tools, and search
2ca490d feat(v2): finish Mission Control and access settings screens
2b79b65 docs(v2): record quality-pass commit hash
4ee2dae test(v2): add Phase 0-3 quality pass before Phase 4
720d515 docs(v2): record Phase 3 test results and next step
5ac15fa feat(v2): add time tracking, reports, and task calendar
9834248 feat(v2): add tasks, assign rules, and mission-control aggregates
73cbcaf feat(v2): add org members, teams, projects, and HR applicant webhook
3f06dce docs(v2): add infra proposal, runbook, tech debt, and disabled deploy workflow
83fd872 feat(v2): add /w workspace shell and stop API URL falling back to production
2357df0 feat(v2): add telemetry, jobs, and best-effort V1 chat writes
d4d9e80 feat(v2): add organizations, permissions, and V2 auth
e8768ab fix(backend): harden V1 P0 defects for Phase 0 PR 0b
```

Stage B feature commits: `2ca490d` (Mission Control + access), `e7da479` (Phases 4–6). Working tree may still show an untracked/unstaged `public/fonts/fa-solid-600.eot` delete; that was not part of Stage B and was not committed.

Phase 7 has not been started.
