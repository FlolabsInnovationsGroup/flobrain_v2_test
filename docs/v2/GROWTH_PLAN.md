# Growth round: features that make FloBrain competitive (2026-10-21)

Owner request: add everything from the competitive review. Seven workstreams, built in parallel in this repo. Each one is local, works in the demo, has tests, and is off by default behind a flag.

| # | Workstream | Flag(s) | Backend | Frontend | Phrase area |
|---|---|---|---|---|---|
| W1 | Automation buddy: workflows from plain language, triggers, steps, approvals, templates; proactive daily brief and nudges | `automations` | `automations` app | `/w/[org]/automations` | `automations` |
| W2 | Channels: WhatsApp and Telegram for buddies; the customer buddy (website chat and WhatsApp) with hand-off to people | `channels`, `customer_buddy` | `channels` app | `/w/[org]/customers`, `/w/[org]/settings/channels` | `channels` |
| W3 | Data buddy: datasets (CSV, Google Sheets, read-only Postgres), questions in plain language, charts with the SQL shown, scheduled reports | `data_buddy` | `datasets` app | `/w/[org]/data` | `data` |
| W4 | Write-back connectors with approval: Google Workspace, Microsoft 365, Jira, HubSpot, Odoo, Zoho | `write_integrations` | `integrations` (+ `actions.plugins`) | `/w/[org]/integrations` | `connectors` |
| W5 | Flo, the router buddy; specialist buddies (Sales, Onboarding, Meeting prep and follow-up, Customer); buddy quality page | `flo_router` | `buddies` | `/w/[org]/buddies`, `/w/[org]/buddies/quality` | `crew` |
| W6 | Academy with an AI coach, industry packs (Education, SMB, Agency) installed in one click, marketplace ratings, AI included per seat meter | `academy`, `packs` | `growth` app (+ `marketplace`) | `/w/[org]/academy`, `/w/[org]/packs` | `academy` |
| W7 | Voice notes in rooms and buddy chat, transcribed on our Whisper server, Egyptian and Gulf Arabic, translated | `voice_notes` | `rooms`, `meetings` (Whisper client) | room composer, buddy composer | `voice` |

Shared pieces prepared first: the four new apps are registered, the nine flags and nine permission keys exist, nav entries exist, `actions.plugins.register_tool` lets any app add an approval-gated tool, and each workstream has its own phrase files.

Rules for every workstream: no secrets in code; external calls only to allowlisted HTTPS hosts; nothing reaches the network in demo or tests; every write that leaves FloBrain or changes data goes through an approval; V1 untouched.
