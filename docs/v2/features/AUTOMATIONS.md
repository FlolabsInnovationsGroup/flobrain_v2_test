# Automations (growth round W1)

Workflows that run on a schedule or when something happens in FloBrain. A workflow is one
trigger and up to 12 steps. People describe a workflow in plain language, review the drafted
steps, and save. Anything that leaves FloBrain waits for an approval.

## Flags and permissions

| | |
|---|---|
| Flag | `automations` (every endpoint answers 501 when off; the inbound webhook answers 404) |
| `automations.use` | See workflows, templates and run history, run a workflow now, ask for a draft |
| `automations.manage` | Create, change, delete, turn on and off, install templates, get webhook secrets, change outgoing-webhook hosts |
| Any member | Opt out of the daily brief and overdue nudges (`/automations/me`) |

A workflow runs with the access of `run_as`: the person who last saved its trigger or steps (or who
turned it back on after the previous person left). Every step re-checks that access at run time
through the same services as the API. Approvals created by a run go to that person.

## Triggers

| Type | Fires when | Notes |
|---|---|---|
| `schedule` | `every`: `day` / `week` (`weekday` 0 = Monday) / `month` (`day` 1–28) at `at` HH:MM, or `hours` (1–24) | Time zone: `trigger.timezone`, else `org.settings.timezone`, else UTC. No free cron. |
| `room_message` | A new message in `room` contains `keyword` (whole word, any case) | `run_as` must be able to read the room |
| `task_created` | A task is created (optional `team`) | `run_as` must be able to see the task |
| `task_blocked` | A task becomes blocked (optional `team`) | Once per blocking (keyed on `blocked_since`) |
| `meeting_ended` | A meeting's `ended_at` is set (optional `room`) | |
| `customer_conversation` | The channels app starts a conversation | See "Hooks for other apps" |
| `webhook` | `POST /api/v2/hooks/automations/{id}` with a valid signature | |
| `manual` | Only "Run now" | |

Receivers are connected from `AutomationsConfig.ready()` to `post_save` of `Task`, `RoomMessage`,
`Meeting` and `ActionProposal`; no other app was edited. They return before any query when the
org has the flag off, and a receiver error is logged, never raised. Writes made by a run never fire
triggers, so a workflow cannot loop. Event triggers are limited to 30 runs per workflow per hour
and deduplicated by event key.

## Steps

| Step | What it does | Approval |
|---|---|---|
| `ai_prompt` | Asks the model; `context` adds data: `blocked_tasks`, `overdue_tasks`, `tasks_due_today`, `recent_tasks` (optionally one `room`), or `trigger` | No (reads only what `run_as` can see) |
| `post_to_room` | Posts as `run_as` (`room` may be `"trigger"` for room and meeting triggers) | No (inside FloBrain) |
| `create_task` | `tasks.services.create_task` as `run_as` | No |
| `notify` | Notification to `people` and/or `roles` (`owner`, `admins`, `team_leads`, `task_assignees`, `room_members`) | No |
| `send_email` | Proposes `automations.send_email` | **Always** |
| `call_webhook` | Proposes `automations.call_webhook` to an allowed https host | **Always**, unless an admin marked the host trusted |
| `wait_for_approval` | Proposes `automations.continue`; the run pauses | **Always** |
| `daily_brief` | Each active member (not opted out) gets their own day: tasks due today, overdue count, today's meetings in rooms they can read, approvals waiting | No |
| `nudge_overdue` | Each assignee of tasks at least `min_days_overdue` late gets one reminder | No |
| `check_budget` | Stops the run quietly unless org AI spend ≥ `threshold_pct` of the monthly org budget | No |

Text fields support `{{steps.N.output}}` (N counts from 1, earlier steps only), `{{trigger.<key>}}`,
`{{workflow.name}}` and `{{today}}`. This is plain substitution; nothing is evaluated.

Validation (`automations/schema.py`) is strict: unknown step types or fields, more than 12 steps,
references to later steps, non-https webhook URLs, hosts not on the allowed list, rooms the editor
can't open and inactive people are all refused with a list of problems.

## Runs and approvals

`engine.process_run` claims a queued run (one processor wins), runs the remaining steps of the
run's own snapshot of the steps, writes `step_log`, and stops at the first failure. Model calls and
outgoing requests do not hold a database transaction. A trusted webhook call records a `started`
marker first, so an interrupted call is never repeated.

An approval step creates an `ActionProposal` (72 h expiry) for `run_as` and a `RunApproval` row; the
run status becomes `waiting_approval` (amber in the UI, with a link to Approvals). When the proposal
is approved, `actions.service` runs the tool once; a `post_save` receiver then queues the rest of the
run. Declined or expired approvals cancel the run; a failed tool fails it. `tick_automations`
reconciles anything missed (expiry, stuck runs).

Registered tools (`actions.plugins.register_tool`, perm `automations.use`):
`automations.send_email` (Django `send_mail`; FloBrain had no sending tool, `email.draft` only
drafts), `automations.call_webhook` (`platform_api.net`: public addresses only, pinned connection,
no redirects, 15 s deadline), `automations.continue`.

AI steps and drafts go through `DirectProvider(org)` (Pulse routing via `brain.llm.routing.complete`),
after `check_ai(org, "direct")` and the platform budget of the person the call is for; usage is
recorded with surface `scheduled_agent`.

## Endpoints (prefix `/api/v2`)

| Method | Path | Perm |
|---|---|---|
| GET, POST | `/orgs/{org}/automations` | use / manage |
| GET, PATCH, DELETE | `/orgs/{org}/automations/{id}` | use / manage / manage |
| POST | `/orgs/{org}/automations/{id}/enable` `{enabled}` | manage |
| POST | `/orgs/{org}/automations/{id}/run` | use (disabled ones: manage); AI send throttle |
| GET | `/orgs/{org}/automations/{id}/runs` | use |
| GET | `/orgs/{org}/automations/runs?status=` and `/runs/{run}` | use |
| POST | `/orgs/{org}/automations/{id}/hook` (create or rotate; secret shown once) | manage |
| GET | `/orgs/{org}/automations/templates` | use |
| POST | `/orgs/{org}/automations/templates/{key}/install` `{room?, emails?, enabled?, name?}` | manage |
| POST | `/orgs/{org}/automations/draft` `{text}` → `{draft, valid, problems}` (never saved) | use |
| GET, PUT | `/orgs/{org}/automations/settings` `{webhook_hosts, trusted_hosts}` | use / manage |
| GET, PUT | `/orgs/{org}/automations/me` `{daily_brief, nudges}` (+ `preview`) | any member |
| POST | `/hooks/automations/{id}` (public) | signature |

Step outputs and trigger payloads in run responses are shown only to `run_as` and managers (they
contain data read with `run_as`'s access). Every change is audited (`automation.create`, `.update`,
`.delete`, `.enable`, `.disable`, `.run`, `.install`, `.hook_rotate`, `.settings`, `.draft`,
`.brief_preferences`); proposals are audited by the actions app as usual.

### Inbound webhook

Headers: `X-FloBrain-Timestamp: <unix seconds>` (±300 s) and
`X-FloBrain-Signature: sha256=<hex HMAC-SHA256(secret, timestamp + "." + raw body)>`, compared in
constant time. Body: a JSON object up to 64 KB; top-level scalar values become `{{trigger.<key>}}`.
30 calls per workflow per minute (429), plus the anonymous V2 throttle. Unknown, disabled or
flag-off workflows all answer 404. Replays of the same timestamp and body are ignored. The secret is
stored with `integrations.crypto` (AES-GCM, bound to the hook and org id); responses only show the
last 4 characters after the one-time reveal.

## Templates

`weekly_blocked_digest` (room), `daily_brief` (proactive), `overdue_nudges` (proactive),
`blocked_task_alert`, `customer_conversation_to_room` (room), `meeting_followup`,
`webhook_to_task` (room), `monthly_report_email` (emails; approval), `budget_alert`.
Proactive ones can be turned on in one click from the gallery; people opt out on the same page.

## Models

`Workflow`, `WorkflowRun` (`steps` snapshot, `step_log`, `current_step`, unique `event_key` per
workflow), `RunApproval`, `InboundHook` (encrypted secret), `AutomationSettings` (allowed and
trusted hosts), `BriefOptOut`. Migration `automations/0001_initial`.

## Scheduling

`python manage.py tick_automations` fires due schedules, processes queued runs and reconciles
approvals; run it every minute next to `tick_agents`. Runs are also queued with the `jobs` app
(`automations.process_run`): inline when jobs are eager, on the worker when one exists, otherwise the
tick picks them up. In demo mode `AutomationsConfig.ready()` appends `tick_automations` to
`demo.ticker.COMMANDS` at startup.

## Demo

`demo/extras/91_automations.py`: four workflows (weekly blocked digest and blocked-task alert on;
monthly report email and daily brief off), ten runs (done, failed, cancelled, and one waiting on an
email approval for Omar). `hooks.example.com` is on the allowed list. The demo model
(`brain/llm/demo_handlers/automations.py`) drafts believable workflows for prompts such as "every
Monday at 9 summarise last week's blocked tasks in Launch room" and "when a task is blocked notify
the lead", and writes labelled summaries for AI steps. In demo mode emails and webhooks are never
sent: the approval result says `simulated`.

## Before production

- Outgoing email needs a real `EMAIL_BACKEND`/SMTP (or a provider) configured; `send_email` uses it.
- `CREDENTIALS_ENCRYPTION_KEY` must be set for inbound webhook secrets (501 otherwise).
- A scheduler must run `tick_automations` every minute (and ideally `run_jobs`).
- Set `org.settings.timezone` (IANA name) for orgs outside UTC, or pass `timezone` per schedule.

## Known limits

- Schedules are simple (daily, weekly, monthly on day 1–28, every N hours); no cron.
- `notify` targets roles or people ids; the editor offers roles only.
- No branching or conditions besides `check_budget`.
- The `customer_conversation` trigger depends on the channels app calling
  `automations.triggers.customer_conversation(org, conversation_id, title, channel)` or exposing a
  `channels.Conversation`/`CustomerConversation` model with `org` (connected automatically if present).
- Notifications use kinds `automation.notice`, `automation.daily_brief`, `automation.nudge`; the
  notifications list shows their `text` but without a link until the shared notification mapper
  learns them.
- A run interrupted mid-step (process crash) is marked failed after 30 minutes; internal steps of
  that run are not retried.
