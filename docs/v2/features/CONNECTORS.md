# Write-back connectors (growth round W4)

Buddies can propose writes to six outside apps. Every write is an approval card: nothing is sent,
created or changed until a person approves it. Off by default.

## What it does

| Provider | Connect with | Actions (risk) |
|---|---|---|
| Google Workspace | OAuth 2 + PKCE, org-wide or per person | Gmail send (high), Gmail draft, Calendar event, Docs create, Sheets append rows, Drive upload (medium) |
| Microsoft 365 | OAuth 2 + PKCE, org-wide or per person | Outlook send (high), Teams channel message (high), Calendar event, OneDrive upload (medium) |
| Jira Cloud | Atlassian OAuth 2 (3LO) | Create issue, comment, transition (medium) |
| HubSpot | OAuth 2 | Create contact, update contact, create deal, log note (medium) |
| Odoo | URL + database + login + API key (JSON-RPC) | Create lead, create task (medium), draft customer invoice (high, never posted) |
| Zoho | OAuth 2 (data center from env) | CRM lead, CRM deal (medium), Books draft invoice (high, never sent) |

Each action declares a JSON schema for its arguments (the strict `actions.schema` subset), the
preview line shown on the approval card (for example `Send email to counsel@example.com: Subject “NDA for review”`),
a risk level, the OAuth scopes it needs, an executor and a demo result. Executors return a link to
what they created.

The integrations page (`/w/[org]/integrations`) has a **Write-back** section: one card per
provider with status, account, connect/disconnect, the scopes it asks for and a switch per action
(admins), then **Recent write actions** with the approval state (amber waiting, green done, rose
failed) and a link to the created object.

## Flags and permissions

- Flag `write_integrations` (org and member flag, plan entitlement). Off: endpoints answer 501, the
  section is hidden, and `check()` refuses every action.
- `integrations.act` (members by default): see the section, connect a personal Google or Microsoft
  account, and have buddies propose actions (each still needs approval).
- `integrations.manage` (admins): connect and disconnect org-wide accounts, turn actions on or off,
  see the whole org's action log.
- The buddy must list the tool in `allowed_tools`, and the `ai_actions` flag must be on for buddy
  chat to offer tools at all (existing rule).

## How a write runs

1. A buddy offered `jira__create_issue` returns a tool call.
2. `actions.service.propose_from_calls` validates the schema and runs our `check()`: flag,
   permission, the org's action switch, extra argument checks (no header injection, decimals,
   ids), a usable connection (personal first for Google/Microsoft, then the org's) and the scopes
   the action needs. It returns the preview line. An `ActionProposal` is stored. Nothing runs.
3. The person approves. `check()` runs again, then `execute()` calls the provider and returns
   `{provider, action, id, url, title, simulated, connection, account}`. A provider error marks the
   proposal failed with a short reason (`Jira answered 400: Project APP does not exist`); a lost
   connection or permission rolls everything back and the proposal stays open.
4. Audit: `action.proposed/executed/failed` (actions app) plus `integration.write` with the tool,
   created object id and link, never the argument content. Connect, disconnect and switches are
   audited as `integration.write.connect`, `integration.write.disconnect`, `integration.write.toggle`.

## Endpoints

All under `/api/v2`.

| Method | Path | Who |
|---|---|---|
| GET | `orgs/{org}/integrations/write` | act or manage |
| POST | `orgs/{org}/integrations/write/{provider}/connect` body `{scope: org\|personal}` (Odoo: `url, database, login, api_key`) | manage for org, act for personal |
| POST | `orgs/{org}/integrations/write/confirm` body `{code}` | the person who started OAuth |
| DELETE | `orgs/{org}/integrations/write/connections/{id}` | manage (org), owner (personal) |
| PATCH | `orgs/{org}/integrations/write/actions/{tool}` body `{enabled}` | manage |
| GET | `orgs/{org}/integrations/write/log?state=waiting\|done\|failed` | act (own rows), manage (org) |
| GET | `integrations/write/oauth/callback/{provider}` | public, `state` only, anon throttle |

## Models (`integrations` app, migration `0003_write_connectors`)

- `WriteConnection` (`write_connections`): org, optional owner (personal), provider, account label,
  scopes, non-secret config (Jira cloud id and site, HubSpot portal, Zoho data center and Books org,
  Odoo URL/database/login/uid), encrypted access and refresh tokens, key version, 4-character hint
  (Odoo key), expiry, status `connected/expired/error/not_set_up`, last error, `demo`, last used.
  One org row and one row per person per provider.
- `WriteOAuthState` (`write_oauth_states`): single-use 10-minute state (SHA-256 hash only),
  encrypted PKCE verifier, parked encrypted token result, confirm-code hash.
- `WriteActionToggle` (`write_action_toggles`): per-org switch per action. No row means on.

Code: `integrations/write/` (`registry`, `catalog/*`, `transport`, `oauth`, `connections`, `tools`,
`models`), `integrations/write_views.py`, `integrations/write_urls.py`. Tools are registered from
`IntegrationsConfig.ready()` with `actions.plugins.register_tool`.

## Security notes

- Tokens and the Odoo API key are AES-256-GCM (`integrations.crypto`), bound to the row id, the
  token kind and the org (a ciphertext copied to another row or swapped access/refresh does not
  decrypt). No API response, log line, error message or `repr` contains a token.
- Outbound calls only through `integrations.write.transport`: https, port 443, no credentials in
  the URL, host on the provider's allowlist, then `platform_api.net.fetch_full` (public addresses
  only, pinned connection, no redirects, 15 s deadline, 1 MB cap). Odoo hosts must be `*.odoo.com`
  or listed in `FLOBRAIN_ODOO_ALLOWED_HOSTS`. Zoho's `api_domain` from the token response is used
  only when it is on the Zoho allowlist.
- One token refresh and one retry on 401; a second 401 or a failed refresh marks the connection
  expired.
- OAuth: authorization code + PKCE S256, state single use and server-side, verifier encrypted,
  fixed redirect URI `{PUBLIC_API_BASE_URL}/api/v2/integrations/write/oauth/callback/{provider}`. The
  callback never connects anything: the person who started the flow confirms with a one-time code
  that only their browser received (same pattern as social accounts), so a forwarded link can't
  attach someone else's account.
- Sheets values are appended with `valueInputOption=RAW` (no formula injection). Email subjects and
  names reject line breaks (no header injection). Odoo and Zoho invoices are created as drafts only;
  calendar invites go out only when `notify_attendees` is true (Google) or guests are listed
  (Outlook), and the preview says so.

## Demo

- `demo/extras/94_connectors.py`: all six providers connected as simulated accounts (labelled
  "demo, simulated", no tokens), Youssef's own Google account, one action turned off
  (Zoho Books invoice), a **Back office buddy** with every connector tool, five connector tools
  added to the Project Management buddy, and a log with done, waiting, failed and rejected rows.
- Approving a demo action runs the simulated executor: an `example.com` link, `simulated: true`,
  and the preview ends with `[demo, simulated]`. Demo connections are refused outside
  `DEMO_MODE` in the demo org. Nothing touches the network.
- Demo model (`brain/llm/demo_handlers/connectors.py`): "create a Jira issue for the Android login
  bug", "send the NDA to counsel by Gmail", "add Mona to HubSpot", invoices in Odoo or Zoho, Teams
  posts, calendar events, Docs, Sheets and uploads become tool calls, so the approval card appears.
- Connecting in the demo creates a simulated connection without OAuth.

## Before production

- Register OAuth apps and set `FLOBRAIN_OAUTH_<PROVIDER>_CLIENT_ID` and `_CLIENT_SECRET` for
  `GOOGLE_WORKSPACE`, `MICROSOFT_365`, `JIRA`, `HUBSPOT`, `ZOHO`. Redirect URI as above.
  Optional: `FLOBRAIN_OAUTH_MICROSOFT_365_TENANT` (default `common`), `FLOBRAIN_OAUTH_ZOHO_DC`
  (`com`, `eu`, `in`, `com.au`, `jp`, `sa`, `ca`), `FLOBRAIN_ODOO_ALLOWED_HOSTS`.
- Google: Gmail send/compose, Drive and Docs scopes are restricted or sensitive and need Google's
  OAuth verification (and a security assessment for restricted scopes). Microsoft:
  `ChannelMessage.Send` and `Files.ReadWrite` need admin consent in many tenants. HubSpot and Zoho
  need a public or private app. Atlassian needs an OAuth 2.0 (3LO) app with `write:jira-work`.
- `CREDENTIALS_ENCRYPTION_KEY` must be set (connect answers 501 otherwise).

## Known limits

- The approval executor runs inside a transaction savepoint. If a call refreshes a token and then
  fails, the refreshed token (and the "expired" mark) roll back with it; the next call refreshes
  again. A provider that rotates refresh tokens with no reuse window may then ask for a reconnect.
- Tools stay in a buddy's offered list while the flag is off; the model may propose them, and the
  proposal is refused with `not_available`. Filtering offered tools by flag needs a change in
  `actions.service.offered_tools` (shared file).
- Uploads are text files only (plain, Markdown, CSV, HTML), up to 200 KB. No attachments on emails.
- Jira uses the first site the account can reach. HubSpot notes associate with one contact.
- Odoo invoices need an existing customer (exact name, case-insensitive); Zoho Books needs a
  customer id. Odoo task needs a project id.
- The OAuth providers' scope strings follow their public docs; verify them against each app
  registration before go-live.
