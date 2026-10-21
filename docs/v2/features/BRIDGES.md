# Slack and Microsoft Teams bridges (M2)

People keep working in Slack or Teams and still get their FloBrain buddies, Flo routing, approvals and notifications there.

- Mention `@FloBrain` in a Slack channel, write to it in a direct message, or type `/flo <question>`. In Teams, mention FloBrain in a channel or chat with it 1:1.
- The buddy runs **as the linked FloBrain person**: their buddies, their sources, their tools, their budget. Unlinked people get a short private notice and nothing else.
- Start with a buddy's name to ask that buddy (`Finance Buddy: what is left in the Q3 budget?`). Otherwise the workspace's default buddy answers; with no default, Flo routes when `flo_router` is on for the person, else the first built-in buddy.
- Actions a buddy proposes become an approval message (Slack Block Kit or a Teams Adaptive Card) in the person's **direct messages**, never in a channel. Approve or Reject there; only that person can decide, and `actions.service` re-checks their access at that moment. The message is updated with the result.
- Optional mirroring to the person's DM: approvals waiting (also ones proposed in FloBrain itself), automation notices and the daily brief, customer escalations. Admins choose which kinds per workspace; each person can turn it off for their link.

## Flags and permissions

- Flag `bridges` (org and member level). Off: every org endpoint returns 501 `not_implemented`; inbound Slack/Teams traffic for that org is ignored (200, nothing processed).
- Permission `bridges.manage` (admins and owners by default): install Slack, connect Teams, manifest, default buddy, mirroring, check, disconnect, see and unlink everyone's links. Missing → 403.
- Every active member can see status and link, confirm, mute or unlink **their own** account.
- Answers also need `ai.use` and the `buddies` flag; approvals need the `ai_actions` flag (same rules as the web app).

## Endpoints

Org (signed in, `/api/v2`):

| Method | Path | Who |
|---|---|---|
| GET | `/orgs/{org}/bridges` | members (admins also get `setup`, `buddies`, secret hints) |
| POST | `/orgs/{org}/bridges/slack/install` | `bridges.manage` → `{authorize_url}` (demo: creates the simulated workspace) |
| POST | `/orgs/{org}/bridges/slack/confirm` `{code}` | the admin who started the install |
| POST | `/orgs/{org}/bridges/teams/connect` `{tenant_id}` | `bridges.manage` |
| GET | `/orgs/{org}/bridges/teams/manifest` | `bridges.manage` (download `manifest.json`) |
| PATCH / DELETE | `/orgs/{org}/bridges/workspaces/{id}` | `bridges.manage` (`default_buddy`, `mirror`, `name`; delete = disconnect) |
| POST | `/orgs/{org}/bridges/workspaces/{id}/test` | `bridges.manage` (Slack `auth.test`; Teams token check) |
| GET / POST | `/orgs/{org}/bridges/links` (`?scope=all` admins) | members; POST `{workspace}` = "Link my Slack/Teams" |
| POST | `/orgs/{org}/bridges/links/{id}/confirm` | the link's own person |
| PATCH / DELETE | `/orgs/{org}/bridges/links/{id}` | own (`mirror`); DELETE also `bridges.manage` |
| POST | `/orgs/{org}/bridges/demo/simulate`, `/demo/decide` | demo server and demo org only (else 404) |

Public (the platform proves itself):

| Method | Path | Check |
|---|---|---|
| POST | `/api/v2/hooks/slack/events` | Slack signature; `url_verification`, `app_mention`, `message.im`, `app_uninstalled`, `tokens_revoked` |
| POST | `/api/v2/hooks/slack/commands` | Slack signature; `/flo` |
| POST | `/api/v2/hooks/slack/interactions` | Slack signature; Approve / Reject buttons |
| POST | `/api/v2/hooks/teams/messages` | Bot Framework JWT |
| GET | `/api/v2/bridges/slack/oauth/callback` | single-use state |

Command: `python manage.py tick_bridges` (every minute) mirrors automation notices and customer escalations.

## Models (`bridges/0001_initial`)

- `BridgeWorkspace`: a Slack team id or Microsoft 365 tenant id bound to one org (conditional unique on platform + external id while not disconnected). Slack bot token encrypted (`channels.vault` → `integrations.crypto`, AAD bound to row and org), `secret_hints` (last 4), `default_buddy`, `mirror` toggles and cursor, `demo`.
- `BridgeLink`: Slack user id or Entra object id ↔ FloBrain person; `pending` until the person confirms in FloBrain, then `active`; `found_via` (`platform` when they wrote to the bot, `flobrain` when they pressed "Link my Slack"); DM channel / Teams 1:1 conversation; `mirror`.
- `BridgeThread`: the FloBrain chat behind one Slack thread / DM / Teams conversation per buddy (keeps context).
- `BridgeEvent`: each inbound event once (unique on workspace + event id); outcome only, the slash-command `response_url` is dropped after use.
- `BridgeCard`: an approval message posted for a proposal (channel and message id, last blocks/card).
- `BridgeOAuthState`: Slack install state (SHA-256 hash, 10 minutes, single use) and the parked, encrypted install result until the starter confirms.

## Security notes

- **Slack requests**: `X-Slack-Signature` = `v0=` + HMAC-SHA256(signing secret, `v0:{X-Slack-Request-Timestamp}:{raw body}`), timestamp within 5 minutes either way, `hmac.compare_digest`. Checked before the body is parsed. Bodies over 256 KB → 413.
- **Teams requests**: PyJWT (2.x, with `cryptography`) checks the `Authorization: Bearer` token: RS256 only; key from the Bot Framework OpenID metadata (`https://login.botframework.com/v1/.well-known/openidconfiguration`, `jwks_uri` must be on `login.botframework.com`), cached 24 h, refetched at most every 5 minutes for an unknown `kid`; key must endorse `msteams`; issuer `https://api.botframework.com`; audience = our app id; `exp` required (5 minutes clock skew, as Microsoft documents); `serviceUrl` claim must equal the activity's `serviceUrl`, and that host must be `*.botframework.com` or `smba.trafficmanager.net`.
- **Outbound**: only `https://slack.com/api/*`, `https://hooks.slack.com/commands/*` (slash-command responses), `login.microsoftonline.com`, `login.botframework.com` and allowlisted Bot Framework service URLs, all through `platform_api.net.fetch` (public IPs only, pinned, no redirects). Teams access tokens are cached in process memory only.
- **Answers stay where asked**: thread reply for a channel mention, ephemeral (`response_url`) for `/flo`, the DM for DMs. Approvals and mirrored notices go only to the person's own DM. Outbound Slack text is escaped (`<`, `>`, `&`), so a model answer can't ping `@channel` or anyone.
- **Linking is never silent**: email match (Slack `users.info` / `users.lookupByEmail` with `users:read.email`; Teams roster `GET /v3/conversations/{id}/members/{id}`) against exactly one active member creates a `pending` link and a FloBrain notification; the person confirms on the settings page. One account per person and one person per account per workspace. Another member can't confirm someone else's link (404).
- **Approvals**: the button must match a card FloBrain posted (channel + message id / reply-to id) for that proposal; the clicker must be the active link of the proposal's own person; then `actions.service.approve/reject` (proposer only, 24 h expiry, executes once, re-checks permissions).
- **Install**: OAuth v2 with single-use hashed state; the callback parks the encrypted token and redirects with a one-time code that only the admin who started can confirm (same pattern as write-back connectors). A Slack team or tenant already bound to another org → 409.
- **Rate limits** (override with `BRIDGES_LIMITS`): hooks 600/min per IP and 300/min per workspace; 10 buddy turns/min per link; one "not linked" notice per sender per 10 minutes; 20 "Link my" lookups per person per hour.
- Secrets never in responses (hints only), logs, fixtures or event rows. Disconnect wipes the token (and calls `auth.revoke`) and revokes every link; Slack `app_uninstalled` does the same.

## Demo

`demo/extras/a2_bridges.py`: a Slack workspace and a Teams tenant, both `demo=True` and labelled "(demo)"; Omar, Layla and Youssef linked in Slack, Layla in Teams, Sara pending in Teams; four past events and one decided approval card. On `/w/{org}/settings/bridges` the "Simulate a Slack mention" box (also Teams) runs the real pipeline as you (event row, buddy turn with the demo model, approval card) with every Slack/Microsoft call captured instead of sent; Approve / Reject on the preview runs the real decision path. Default text asks the Project Management Buddy to create a task, so an approval card appears. Install/connect in demo creates simulated rows; no secrets are stored.

## Production setup

### Server environment

| Variable | What |
|---|---|
| `FLOBRAIN_SLACK_CLIENT_ID`, `FLOBRAIN_SLACK_CLIENT_SECRET` | Slack app, Basic Information |
| `FLOBRAIN_SLACK_SIGNING_SECRET` | Slack app, Basic Information, Signing Secret |
| `FLOBRAIN_TEAMS_APP_ID`, `FLOBRAIN_TEAMS_APP_SECRET` | Azure Bot's Microsoft App ID and a client secret of its Entra app registration |
| `FLOBRAIN_TEAMS_TENANT_ID` | Optional. Set for a single-tenant bot (tokens from `login.microsoftonline.com/{tenant}`); unset uses `botframework.com` (legacy multi-tenant) |
| `PUBLIC_API_BASE_URL`, `FRONTEND_BASE_URL`, `CREDENTIALS_ENCRYPTION_KEY` | already used by FloBrain; must be https in production |
| `JOBS_WORKER_ENABLED=true` + `manage.py run_jobs` | so events are processed by the worker (without it they run on a background thread so Slack still gets its answer within 3 s) |

Without the Slack or Teams variables the settings page shows "Needs setup" with the names of the missing variables, and the endpoints answer 501 `not_configured`.

### Slack app

1. https://api.slack.com/apps → Create New App → From an app manifest → pick a workspace → paste (replace `API` with `PUBLIC_API_BASE_URL`):

```json
{
  "display_information": {
    "name": "FloBrain",
    "description": "Your FloBrain buddies and approvals in Slack",
    "background_color": "#08070f"
  },
  "features": {
    "app_home": { "home_tab_enabled": false, "messages_tab_enabled": true, "messages_tab_read_only_enabled": false },
    "bot_user": { "display_name": "FloBrain", "always_online": true },
    "slash_commands": [
      {
        "command": "/flo",
        "url": "https://API/api/v2/hooks/slack/commands",
        "description": "Ask your FloBrain buddy",
        "usage_hint": "[your question]",
        "should_escape": false
      }
    ]
  },
  "oauth_config": {
    "redirect_urls": ["https://API/api/v2/bridges/slack/oauth/callback"],
    "scopes": {
      "bot": ["app_mentions:read", "chat:write", "commands", "im:history", "im:read", "im:write", "users:read", "users:read.email"]
    }
  },
  "settings": {
    "event_subscriptions": {
      "request_url": "https://API/api/v2/hooks/slack/events",
      "bot_events": ["app_mention", "message.im"]
    },
    "interactivity": { "is_enabled": true, "request_url": "https://API/api/v2/hooks/slack/interactions" },
    "org_deploy_enabled": false,
    "socket_mode_enabled": false,
    "token_rotation_enabled": false
  }
}
```

2. Slack verifies the events URL with `url_verification` (FloBrain answers it once the signing secret is set).
3. Copy client ID, client secret and signing secret into the environment; restart.
4. To install in more than one Slack workspace: Manage Distribution → activate public distribution (Slack review is needed only for the Slack Marketplace).
5. In FloBrain: Settings → Slack and Teams → Install in Slack → approve in Slack → back in FloBrain the install is confirmed. Ask people to press "Link my Slack". `app_uninstalled` / `tokens_revoked` arrive automatically and disconnect the workspace.

### Azure Bot (Teams)

1. Azure portal → Create a resource → **Azure Bot** → Type of App **Single Tenant** (new multi-tenant bots can't be created since July 2025) → create a new Microsoft App ID.
2. Bot → Configuration → Messaging endpoint `https://API/api/v2/hooks/teams/messages`. Note the Microsoft App ID (and the App Tenant ID).
3. Bot → Configuration → Manage Password (the Entra app registration) → Certificates & secrets → New client secret.
4. Bot → Channels → add **Microsoft Teams** (commercial).
5. Set `FLOBRAIN_TEAMS_APP_ID`, `FLOBRAIN_TEAMS_APP_SECRET`, `FLOBRAIN_TEAMS_TENANT_ID`; restart.
6. In FloBrain: Settings → Slack and Teams → Microsoft 365 tenant ID (Entra admin center, Overview) → Connect Teams.

### Teams app

1. Download the manifest from the settings page (schema 1.17; `bots[0].botId` = the app id; personal, team and group chat scopes; a stable app `id` derived from the org and bot id).
2. Add `color.png` (192×192) and `outline.png` (32×32, white on transparent), zip the three files at the top level.
3. Teams admin center → Teams apps → Manage apps → Upload new app (or Teams → Apps → Manage your apps → Upload an app, if custom app upload is allowed). Allow it in the app permission policy.
4. People open FloBrain in Teams and write anything once; their account is matched by email (`email` / `userPrincipalName` from the roster) and they confirm it in FloBrain.

## What is simulated, and known limits

- Demo: every Slack and Microsoft call is captured, never sent; demo rows never accept real webhooks.
- Not built: Slack Enterprise Grid org-wide installs, Slack token rotation, Teams `Action.Execute` (Universal Actions) and SSO, Teams message extensions, editing a proposal before approving from Slack/Teams (open FloBrain for that), files and voice notes from Slack/Teams.
- Teams uses one platform bot (env); each org binds its tenant. A single-tenant bot works only inside its own tenant, so a multi-company deployment needs one bot per tenant (not supported yet).
- Teams email matching relies on the roster's `email`/UPN equalling the FloBrain email; guests and aliases need "Link my Teams" after writing to the bot.
- Mirroring of automation notices and escalations depends on `tick_bridges` being scheduled (see the lead's ticker and Helm cronjob); approvals are mirrored immediately.
- Answers to a channel mention are visible to that channel, as people expect in Slack; the buddy still uses only the asker's access, so people should ask sensitive questions in a DM.
- Verify the Bot Framework issuer and token endpoint against Microsoft's current docs before go-live.
