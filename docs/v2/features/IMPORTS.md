# Imports from Slack, Notion and Google Drive (M6)

A new customer brings their history in on day one: Slack channels become rooms with their messages, Notion pages and Google Docs become documents. Everything is labelled with where it came from, searchable through the normal knowledge index, limited to the people who can open the room, and every import can be undone.

## Flags and permissions

| | |
|---|---|
| Flag | `imports` (off by default; on in the demo). Flag off: every endpoint answers 501 `not_implemented` |
| `imports.run` | Everything on this page: upload, preview, run, cancel, resume, undo, history (owners and admins by default; members don't have it) |
| Creating teams | Mapping a Slack channel to a **new team** also needs org owner or admin |
| Target rooms | Messages and documents only go to rooms the importer can open (`rooms.services.user_can_access_room`) |
| Support sessions | Impersonated sessions can read the page but can't change anything (403) |

## Sources

| Source | How | What it becomes |
|---|---|---|
| Slack workspace export (ZIP) | Upload (`source=slack`) | Public channel → a team's room (an existing team, or a new team named after the channel with the matched people). Private channel (`groups.json`, only with `include_private`) → a private room whose members are the matched people only. DMs (`dms.json`, `mpims.json`) only with `include_dms`, same rule. A channel with nobody matched is skipped. |
| Notion export ZIP ("Markdown & CSV") | Upload (`source=notion_zip`) | One document per page (`.md`) and per database (`_all.csv` preferred), in a chosen room. One level of inner ZIP (newer exports) is read with the same rules. |
| Notion via the existing connection | `connectors` Notion connection (internal integration token, encrypted) | Pages and databases the integration can see (`POST /v1/search`); a page's blocks become Markdown (headings, lists, to-dos, quotes, code, tables as `a \| b`), a database becomes one table document (up to 500 rows). |
| Google Drive via the Google Workspace connection | `integrations/write` Google connection, personal first, then the org's | Google Docs (exported as Markdown, plain text as fallback), DOCX, text, Markdown, CSV and HTML files. PDF only when `pypdf` is installed. |
| Google Takeout ZIP or single files | Upload (`source=files`, up to 20 files) | Same file types as Drive. |

People are matched by email (case-insensitive) to **active members of this org only**. Anyone else keeps no account: their messages have no author and start with `Imported: Name`.

Slack details: original timestamps and authors; joins, leaves, topic/purpose/name changes, pins and other housekeeping are skipped; bot and app messages are skipped unless `include_bots`; `message_changed` updates the text (marked "(edited)"), `message_deleted` drops it; thread replies start with `↳ Reply in thread: “first words of the parent”`; reactions become one line (`Reactions: :tada: 3`); files become `File: name (permalink)` links, never downloaded; `<@U…>` becomes `@Name`, `<#C…|x>` becomes `#x`, `<url|label>` becomes `label (url)`, unknown schemes are dropped. Each room gets one announcement: "Imported from Slack #name: N messages from … to …. Imported by …".

Documents start with a source line: `Source: Notion · https://www.notion.so/<id>`, `Source: Google Drive · <webViewLink>`, `Source: Google Takeout (file.docx)` or `Source: uploaded file (file.md)`.

## Flow

1. **Upload** (`POST /imports/upload`): streamed by Django to a temp file, size checked from `Content-Length` before the body is read, stored in private storage (`content_studio.storage`, key `imports/<org>/<run>/<n>-<name>`; keys are never returned). One import may be active per org (409 `busy`), 20 uploads per hour per org (429).
2. **Analyse** (job `imports.analyze`): safe unzip, preview. Slack: channels with kind, message and thread counts, date range, members and matched counts, a suggested team (same name); people with matched or "Imported: Name". Documents: items with kind, size and whether they can be read. The preview holds names and counts, never message text.
3. **Map and start** (`POST /imports/{id}/start {mapping}`): Slack `{"channels": {"C…": {"target": "team", "team_id": …} | {"target": "new_team"} | {"target": "private"} | {"target": "skip"}}, "include_private", "include_dms", "include_bots"}`. Documents `{"room_id", "refs": [...]}` (default: everything readable). Validated on the server (public channels can't become private rooms, private ones can't become teams, the team room must be one you can open).
4. **Run** (job `imports.run`): batches of 500, progress after each batch (`progress: {done, total, current}`), cancel checked between batches. With a worker the job runs in 4-minute slices (`IMPORTS_JOB_SECONDS`) and queues the next slice; a lease (`lease_until`) keeps two workers off the same run. In eager mode (tests, local demo) it runs inline.
5. **Cancel** (`/cancel`): a queued import stops at once; a running one at the next batch. What is in stays until undone.
6. **Resume** (`/resume`): a failed or stopped import runs again; everything already imported is skipped.
7. **Undo** (`/undo`, job `imports.undo`): deletes exactly what the run created, recorded in `ImportedObject`: messages, documents, announcements, room members, team memberships, then rooms and teams it created, unless someone has since written in them (they stay, counted as `kept_containers`). The stored upload is deleted.

**Idempotency:** every created message, document, room, team and announcement has a source key (`slack:<channel>:<ts>`, `slack:<channel>`, `notion:<32 hex id>`, `drive:<file id>`, `file:<sha256>`), unique per org. A second import of the same export (or a resumed one) skips existing keys and reuses the rooms and teams the first one made. Notion pages imported through the export and through the API share the same key. Undoing a run frees its keys.

## Zip safety (`imports/safezip.py`)

Nothing is extracted to disk; members are read into memory one at a time. The whole archive is refused when any entry has an absolute path (`/x`, `C:x`), a `..` part, a backslash or NUL, is a symlink, is encrypted, when there are more than 20 000 entries (`IMPORTS_MAX_ZIP_ENTRIES`), more than 2 GB unpacked (`IMPORTS_MAX_UNPACKED_MB`), one member over 200 MB (`IMPORTS_MAX_ZIP_MEMBER_MB`), or an entry past 1 MB with a compression ratio over 100 (`IMPORTS_MAX_ZIP_RATIO`). Reads stop at the declared size, so a member that lies about its size is refused too. DOCX files go through the same checks and their XML through `defusedxml`.

## Endpoints (prefix `/api/v2/orgs/{org}/imports`)

| Method | Path | |
|---|---|---|
| GET | `/meta` | limits, rooms and teams you can import into, Notion connections, Drive status (`ready`, `needs_scope`, `not_connected`), PDF support, the active run |
| GET | `` | history (last 100) |
| POST | `/upload` | multipart `source` + `file` (one ZIP, or up to 20 files for `files`) |
| POST | `/sample` | `{source: slack \| notion}`: the bundled demo export (demo org only, 403 elsewhere) |
| GET, DELETE | `/{id}` | detail with preview and mapping; discard a run that added nothing |
| POST | `/{id}/start`, `/{id}/cancel`, `/{id}/resume`, `/{id}/undo` | see Flow |
| GET | `/notion/pages?connection_id=&q=` | pages and databases the Notion integration can see |
| POST | `/notion` | `{connection_id, room_id, items: [{id, type: page \| database}]}` (1 to 200) |
| GET | `/drive/files?q=&page_token=` | importable Drive files; `q` is escaped into the Drive query |
| POST | `/drive` | `{room_id, file_ids}` (1 to 200) |

Without a worker (and outside eager mode) starting, resuming or undoing answers 503 `unavailable` and leaves the run as it was.

## Models (`imports/0001_initial`)

- `ImportRun`: org, source, status (`analyzing`, `ready`, `queued`, `running`, `done`, `failed`, `cancelled`, `undoing`, `undone`), files (storage keys, private), preview, mapping, progress, counts, error (`code: readable text`), cancel flag, lease, demo flag, who and when.
- `ImportedObject`: run, kind, object id, source key (unique per org and kind when set).

## Indexing and visibility

Documents are created with a normal save, so `knowledge.signals` indexes them. Messages are bulk-created (a normal save would send one push notification per imported message in private rooms through `rooms.signals`) and each one is queued on the same `knowledge.index` job the signal uses, only when the org's `memory_search` is on. Chunks carry the room, so search and ask keep respecting room access. Undo deletes through the ORM, so the knowledge delete signals remove the chunks and vectors.

## Audit, logs and notifications

Audit actions: `imports.uploaded` (source, file count, bytes), `imports.started` (source, number selected), `imports.finished` / `imports.failed` / `imports.cancelled` (source, counts), `imports.cancel_requested`, `imports.resumed`, `imports.undo_requested`, `imports.undone` (removed counts), `imports.discarded`. Payloads and logs hold ids and counts only: no message text, no file names, no channel names. The importer gets an `import_finished` notification.

## Demo

- `imports/fixtures/slack_export/`: 7 fake people (5 match the demo accounts by email, 2 don't, plus a bot), `#general` and `#engineering` (public) and `#design-crit` (private), 150 messages over three weeks with threads, reactions, edits, file links, mentions, a join and a bot message (both skipped).
- `imports/fixtures/notion_export/`: a handbook page with two subpages (callout, table, code, links, image) and a customers database.
- `demo/extras/a6_imports.py` imports the Notion export into the Design room, so the history shows a finished import with undo. The Import page offers "Try the sample Slack export" and "Try the sample Notion export"; both run and undo without network. Connected Notion and Google Drive use the existing demo connections and return canned pages and files.

## Before production

- Google Drive listing needs the read scope `https://www.googleapis.com/auth/drive.readonly` on the Google Workspace provider (today it asks only `drive.file`, which can't list other files). Until then real connections show "needs Drive read access" and people use Takeout or uploads. Adding the scope also means Google's OAuth verification for a restricted scope.
- PDF text needs `pypdf` in `requirements.txt` (not installed; PDFs are listed and skipped with a reason).
- A worker (`manage.py run_jobs`, `JOBS_WORKER_ENABLED=True`) and object storage (`CONTENT_STORAGE=s3`) are needed for 500 MB uploads; the reverse proxy must allow request bodies of that size (`client_max_body_size`).
- Notion API imports use the token of an existing Notion connection; pages must be shared with that integration.

## Known limits

- Rooms have no threads: replies are flat messages with the parent's first words.
- Slack files, Notion attachments and Drive images are links, not copies. Signed Notion file links are dropped because they expire.
- Slack user groups, canvases, huddles and Enterprise Grid org-wide exports are not handled; emoji stay as `:name:`.
- A public channel goes to an existing or new team; there is no org-wide room kind.
- Notion databases become one table document (500 rows); nested pages inside a page are listed as "Subpage: title", not imported recursively through the API (the export ZIP does include them).
- Undo keeps a room or team someone has written in since the import.
