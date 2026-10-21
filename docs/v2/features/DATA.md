# Data buddy (W3)

Ask questions about spreadsheets and databases in plain language. Every answer comes with the chart and the SQL that produced it. Answers can be saved as cards, and cards can be sent as weekly or monthly reports.

## Flags and permissions

| | |
|---|---|
| Flag | `data_buddy` (off by default; on in the demo). Flag off: every endpoint answers 404 |
| `data.use` | See datasets shared with you, ask, save cards, schedule reports (members have it) |
| `data.manage` | Add, refresh, re-share and delete sources (admins and owners) |
| Private hosts | Only an org owner or admin with `data.manage` can allow PostgreSQL hosts on private networks (`org.settings.data_buddy.allow_private_hosts`) |

Sharing per dataset: **Everyone** (org), **One team** (team members and org admins), **Only me** (the owner only; admins do not see it). Cards and reports follow the dataset: a card is visible to whoever can see its dataset; a report recipient is notified only if they can see every dataset in it.

## Sources

| Source | How it is stored | Limits |
|---|---|---|
| CSV / XLSX upload | Copied into one SQLite file per dataset (`DATASETS_DIR`, default `media/private/datasets/<org>/`), table `data`. Never in the main database schema | 10 MB (`DATASETS_MAX_UPLOAD_MB`), 200 000 rows (`DATASETS_MAX_ROWS`), 100 columns, first sheet only for XLSX |
| Google Sheet | A "Publish to the web" CSV link (`https://docs.google.com/spreadsheets/d/e/<id>/pub?output=csv`, optional `gid`, `single`). Fetched like an upload into the same SQLite store; refreshed on demand and on a schedule (0, 1, 6, 12, 24 or 168 hours) | Same as uploads |
| PostgreSQL | Queried live, read-only. The connection string is AES-GCM encrypted with `integrations.crypto` (bound to dataset and org id) and only a masked hint is returned (`postgresql://user:••••@host:5432/db`) | Up to 20 tables, 5 s statement timeout (`DATASETS_PG_STATEMENT_TIMEOUT_MS`) |

Column types are inferred: integer, decimal, yes/no, date, date and time, text. Header names become safe SQL names (`Ticket ID` → `ticket_id`; SQL words get a `col_` prefix).

## Asking

`POST /api/v2/orgs/{org}/data/ask {dataset_id, question}`

1. The model gets the schema (columns, types, 5 sample rows) as quoted data and writes one SQL query (`[flo:data-sql]` prompt).
2. FloBrain checks it (`datasets/sqlguard.py`): one statement, `SELECT`/`WITH` only, no comments, no `$`, backticks or brackets, no write, DDL, `ATTACH`, `PRAGMA`, `INTO`, row-lock or transaction keywords, no catalog names (`sqlite_*`, `pg_*`, `information_schema`), no dangerous functions (`load_extension`, `readfile`, `pg_sleep`, `dblink`, `set_config`, ...), and every table after `FROM`/`JOIN` must belong to the dataset or be a `WITH` name. On PostgreSQL only functions on an allow list may be called.
3. It runs with a row cap (5 000, `DATASETS_QUERY_MAX_ROWS`) and a time limit (5 s, `DATASETS_QUERY_SECONDS`):
   - SQLite: read-only URI, `query_only`, `set_authorizer` that allows only `SELECT`, `READ` (not `sqlite_*`, not `temp`), `FUNCTION` (minus a deny list) and recursive CTEs; a progress handler stops it at the deadline.
   - PostgreSQL: connection pinned to the checked address (`hostaddr`), TLS required for public hosts, `default_transaction_read_only=on`, `statement_timeout`, a read-only session, and a server-side cursor (`DECLARE ... CURSOR FOR`, which PostgreSQL accepts only for one SELECT). Always rolled back.
4. The model proposes `{answer, chart: {type: bar|line|table|number, x, y, series}}` from the first 30 rows (`[flo:data-chart]` prompt). The chart is checked against the result columns (y must be numeric, series must be another column); an invalid one is replaced by a chart derived from the result (`chart_fixed: true`).

Response: `sql`, `columns`, `rows` (up to 1 000), `row_count`, `truncated`, `chart`, `chart_fixed`, `answer`. A rejected query returns 422 `sql_rejected` with the SQL that was not run. AI calls are throttled like other AI sends and recorded as usage with surface `data_buddy`.

## Endpoints (prefix `/api/v2/orgs/{org}/data`)

| Method and path | What |
|---|---|
| `GET meta` | Limits, `can_manage`, `is_admin`, `allow_private_hosts`, `postgres_available` |
| `PATCH settings` | `{allow_private_hosts}` (owner or admin) |
| `GET datasets` | Datasets you can see |
| `POST datasets/upload` | multipart `file`, `name`, `visibility`, `team` |
| `POST datasets/sheet` | `{url, name, visibility, team, refresh_every_hours}` |
| `POST datasets/postgres` | `{dsn, tables?, name, visibility, team}` (501 without an encryption key) |
| `GET/PATCH/DELETE datasets/{id}` | Detail with schema, sample rows and cards; rename, re-share, schedule; delete (file removed) |
| `POST datasets/{id}/refresh` | Sheet: fetch again; PostgreSQL: re-read tables; upload: 409 |
| `POST ask` | See above |
| `GET/POST cards`, `PATCH/DELETE cards/{id}`, `POST cards/{id}/run` | Saved questions. The SQL is checked and run again on save |
| `GET/POST reports`, `PATCH/DELETE reports/{id}`, `POST reports/{id}/run` | Weekly (weekday, hour UTC) or monthly (day 1 to 28, hour UTC); recipients; optional room |

## Models

`Dataset`, `SavedQuestion` (card), `Report` (cards, recipients, cadence, `next_run_at`), `ReportRun` (results, notified count, room post). Migration `datasets/0001_initial`.

## Reports and scheduled refresh

`python manage.py run_data_reports` (hourly, safe to repeat) refreshes sheets that are due, then sends reports that are due. Each row is claimed with a conditional update on `next_run_at`, so two runners never send the same report twice. A report re-runs each card's saved SQL as its creator (no model call), creates a notification `data.report` for the creator and recipients who can see every dataset (with push), and, if a room is set, posts a summary in the room as the creator (the creator chose the room and must still be able to post there). Reports are skipped when the flag is off or the creator lost access.

## Buddy tool

`data.ask` is registered through `actions.plugins.register_tool` from `DatasetsConfig.ready()`: risk `read`, permission `data.use`, arguments `{question, dataset? (id), dataset_name?}`. It runs the same pipeline on datasets the user can see and returns the answer, SQL, the first 50 rows and the chart. Like every tool it only appears for buddies that list it in `allowed_tools`.

## Demo

`demo/extras/93_datasets.py` builds three datasets from CSV made in the seed (through the real upload reader): **Sign-ups by week and channel** (12 weeks × 5 channels, everyone), **Support tickets** (140 tickets, shared with Engineering), **Q4 budget lines** (looks like a Google Sheet; the demo never fetches it and refresh says so). Four cards and a weekly report "Monday numbers" (Monday 07:00 UTC, posted in the Engineering room) with one past run. The demo model (`brain/llm/demo_handlers/datasets.py`) maps common questions ("sign-ups this week vs last", "by channel", "tickets by status", "budget left by category", "over budget", ...) to correct SQL and answers anything else with a safe `SELECT * ... LIMIT 20`; answers start with "(Demo answer)".

## Before production

- `CREDENTIALS_ENCRYPTION_KEY` must be set for PostgreSQL sources.
- `DATASETS_DIR` should be on a persistent, private volume and included in backups (it holds org data).
- Schedule `run_data_reports` hourly (compose ticker / Helm cronjob; see the hook below).
- Give connected databases a role that can only `SELECT` the shared tables. The checks here are the second line, not the first.

## Known limits

- XLSX: first sheet only, no formulas recomputed, dates detected from built-in and simple custom formats.
- Date formats other than ISO (`2026-10-21`) stay text.
- A sheet must be published to the web; private sheets need Google OAuth (not built).
- PostgreSQL schema is re-read only on refresh; row counts are not shown for databases.
- The SQL text guard is a strict tokenizer, not a full parser: it can refuse valid queries (for example a column named like a denied keyword without quotes).
- The `data.ask` buddy tool goes through the normal proposal flow; showing read-only tool results inline in buddy chat depends on the buddy chat runner.
- Charts show at most three colored series; more fold into "Other" (the table view has everything).
