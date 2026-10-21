# Running the FloBrain demo locally

The demo is a ready-made company, **Nile Labs**, with one person per role. On the sign-in page you pick a seat (owner, admin, team lead, member) or **Take the full tour**, and you see FloBrain exactly as that person does. A bar at the top lets you switch seats or start the demo over.

Demo mode is **off by default** and must never be switched on in production: anyone who can reach the API can sign in as the demo users.

## Quickest way: one click

From a copy of this repository, with Python 3.11+ and Node.js 20+ installed:

- **Windows:** double-click `run-demo.bat` at the repository root.
- **macOS / Linux:** run `./run-demo.sh`.

The script installs the Python and website packages only when they are missing or changed, builds a local SQLite demo database (`flobrain-core/backend/demo.sqlite3`), starts the API on port 8000 and the website on port 3000, and opens the sign-in page. Close the two windows (Windows) or press Ctrl+C (macOS/Linux) to stop. Delete `demo.sqlite3` to start from a clean demo.

The manual steps below do the same thing by hand (and let you use PostgreSQL).

## What you need

- Python 3.11+ with the backend requirements, Node 20+.
- PostgreSQL 15/16 with `pgvector` (recommended), or SQLite for a quick look.

## 1. Backend (PowerShell, from `flobrain-core/backend`)

```powershell
$env:DEBUG="True"
$env:ALLOW_INSECURE_AES_MASTER_KEY="1"
$env:SECRET_KEY="local-demo-secret-key-that-is-long-enough-1234567890"
$env:CREDENTIALS_ENCRYPTION_KEY=("ab" * 32)
$env:DEMO_MODE="True"          # turns on demo sign-in and the demo org
$env:DEMO_AI="True"            # built-in demo model: no AI key, no network
$env:AI_PROVIDER_BACKEND="direct"
$env:EMBEDDINGS_BACKEND="fake" # memory search works without an embeddings server
$env:EMBEDDINGS_MODEL="fake-embedder"
$env:KNOWLEDGE_VECTOR_STORE="json" # needed on SQLite (no pgvector); leave unset on PostgreSQL with pgvector
$env:CONTENT_STORAGE="local"
$env:CORS_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
$env:PUBLIC_API_BASE_URL="http://127.0.0.1:8000"   # the demo SSO sign-in page and SAML addresses use it
$env:FRONTEND_BASE_URL="http://localhost:3000"
$env:CERTIFICATE_SIGNING_KEY="<32 random bytes, base64>"  # optional: the demo then includes a signed certificate
# PostgreSQL (or set $env:DB_ENGINE="sqlite" instead of the next line)
$env:DB_HOST="localhost"; $env:DB_NAME="flobrain_demo"; $env:DB_USER="flo_user"; $env:DB_PASS="flo_password"

python manage.py migrate
python manage.py seed_demo      # optional: the first demo sign-in also builds it
python manage.py runserver 127.0.0.1:8000
```

## 2. Website (from `flobrain-website`)

```powershell
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
npm ci
npm run dev
```

Open <http://localhost:3000/w/signin>.

## What the demo contains

| Role | Person | Try first |
|---|---|---|
| Owner | Nadia Hassan | AI policy, billing, SSO and provisioning, export |
| Admin | Omar Khaled | Approve the pending marketplace listing, access, support sessions, Sara's deletion request |
| Team lead | Layla Mansour (Engineering) | Draft and post the weekly report, run the Monday agent |
| Member | Youssef Adel | Ask the org, propose a task with a buddy and approve it, Content Studio, Privacy (download your data) |

Also seeded: two teams, one project, tasks with priorities and due dates (one blocked, one due tomorrow, one overdue), time across categories with one entry waiting for approval, team, project, direct and group rooms with mentions, announcements and room AI threads, documents with history and an attachment, meetings (see below), skills, built-in buddies plus a member's own buddy, a pending AI action, a scheduled agent, a brand kit and the FLOQ template, learning, leads and commission, a week of Pulse usage, a GitHub-style connection, privacy choices (Youssef keeps his time descriptions private), a pending deletion request from Sara and a retention policy, two people waiting from HR, permission grants and requests, AI keys on the demo provider, usage and budgets (Engineering at 85 %), a buddy share request, a demo Notion masterclass database, a signed certificate, a Content Studio project with a finished render and a sandbox social account, a connected demo MCP agent, incidents, webhook deliveries in a demo inbox, plans and invoices. Every feature flag is on.

Things that work without any outside service in the demo:

- **Calls and recording:** joining a meeting opens a demo call with the other room members as simulated people. Recording, then stopping, makes one sample recording per speaker, a transcript by speaker, a summary and action items.
- **Meeting assistant:** inviting it to a Zoom, Meet or Teams link walks through joining, waiting in the lobby and recording, in about 40 seconds, then leaves a transcript and summary.
- **SSO:** SAML is connected to a demo identity provider. Sign out, choose "Sign in with SSO" with `owner@demo.flobrain.example`, and pick who signs in.
- **Scheduled work:** reminders, scheduled agents, webhook retries, content renders and Pulse checks run inside the API every minute (`DEMO_TICKS=0` turns this off).
- **Notifications:** new ones pop up in the app; "Turn on push" lets the browser show them while the tab is open.
- **Renders, voiceover, social posts, outside agents, webhooks, billing checkout:** demo versions, each labelled "demo".

## Meetings in the demo

Seeded: "Weekly launch sync" (ended, with a transcript by speaker, a summary and action items you can turn into tasks), "Launch standup (live now)" that anyone in the room can join, and "Pilot call with Acme (example)" that the meeting assistant attended. Without the meetings stack, calls and recordings use the demo path described above. To try a real call locally, run LiveKit with `livekit-server --dev` and start the API with `LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret`; with `ASR_BACKEND=http` and the `whisper-server/` running, recordings are transcribed for real.

## How the demo is kept safe

- Demo sign-in only issues tokens for the seeded demo users (`demo_accounts` table). They have no usable password.
- Everything is 404 when `DEMO_MODE` is off. Django warns (`flobrain.W010`) if demo mode runs without `DEBUG`.
- The demo model (`DEMO_AI`) answers with clearly labelled sample text, and proposes a task when you ask for one. Proposals still need approval.
- "Start the demo over" deletes and rebuilds only the `demo` org and the `@demo.flobrain.example` users, at most once a minute.
- There is no platform-staff demo seat, because platform admins can see every org on the server.
