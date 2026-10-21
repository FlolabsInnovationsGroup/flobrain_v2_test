# Channels and the customer buddy (growth round W2)

People talk to their buddies from WhatsApp and Telegram, and answer their own approvals by
replying. Customers talk to the customer buddy on the website chat, WhatsApp or Telegram; it
answers only from documents an admin marked public for customers and hands the conversation to a
person when it is not sure. Everything is off by default.

**Until the production steps at the end are done, WhatsApp and Telegram are simulated.** The demo
connections never call Meta or Telegram, and a real connection only works once its provider side
is set up.

## Flags and permissions

| | |
|---|---|
| Flag `channels` | Connections, linking, webhooks. Off: org endpoints answer 501, webhooks 404 |
| Flag `customer_buddy` | Inbox, customer settings, the website chat, customer messages on WhatsApp/Telegram. Off: 501 (org endpoints), 404 (public chat) and customer messages are ignored |
| `channels.manage` (admins) | Connect, change, test and disconnect channels; customer buddy settings |
| `customers.view` (admins) | See every customer conversation |
| `customers.reply` (members by default) | Reply, approve drafts, take over, hand back, resolve, assign. Without `customers.view` a person sees only conversations assigned to them or to a room they can open |
| `ai.use` + flag `buddies` | Link my phone and talk to my buddy from it |
| flag `ai_actions` | Answer approvals by reply |

## Endpoints

Org endpoints (`/api/v2/orgs/{org}/...`, signed in):

| Method and path | What |
|---|---|
| `GET/POST channels/connections` | List or connect (`kind`: `whatsapp`, `telegram`, `website`; `config`; `secrets`; `serve_team`; `serve_customers`; `team_buddy`) |
| `PATCH/DELETE channels/connections/{id}` | Change (secrets replaced only when given) or disconnect (secrets wiped, everyone unlinked, site key removed) |
| `POST channels/connections/{id}/test` | Check the credentials with the provider (simulated for demo) |
| `GET/POST channels/links`, `DELETE channels/links/{id}` | My links; make a one-time 6-digit code; unlink |
| `GET/PUT channels/customer-settings` | Auto reply, hand-off room, blocked topics, name, greeting, public documents |
| `GET customers/conversations?status=open\|waiting_human\|resolved\|drafts&mine=1` | Inbox |
| `GET customers/conversations/{id}` | One conversation with drafts and citations |
| `POST customers/conversations/{id}/reply\|takeover\|handback\|resolve\|assign` | Staff actions (`assign`: `{assignee?, room?}`) |
| `POST customers/conversations/{id}/messages/{message}/approve\|reject` | Send (optionally edited `text`) or discard a buddy draft |
| `POST channels/demo/simulate` | Demo org on a demo server only: `{connection, text, from: "customer"\|"me"}` |

Provider webhooks (no sign-in, the provider proves itself):

| | |
|---|---|
| `GET /api/v2/hooks/whatsapp/{connection}` | Meta's challenge: `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge` |
| `POST /api/v2/hooks/whatsapp/{connection}` | `X-Hub-Signature-256: sha256=HMAC(app secret, raw body)` |
| `POST /api/v2/hooks/telegram/{connection}` | `X-Telegram-Bot-Api-Secret-Token` equals the stored secret token |

Website chat (public, no sign-in):

| | |
|---|---|
| `GET /api/v2/public/chat/{site_key}?embed=<parent origin>` | Name, greeting, whether this page may embed it |
| `POST /api/v2/public/chat/{site_key}/messages` | `{text, conversation?, embed_origin?}`; the first message returns the conversation token once |
| `GET /api/v2/public/chat/{site_key}/messages?conversation=<token>` | Messages the customer may see (never drafts) |

Frontend: `/w/[org]/customers` (inbox), `/w/[org]/settings/channels` (connections, linking, customer
buddy settings, demo simulator), `/p/chat/[siteKey]` (the chat page) and `public/v2/widget.js`:

```html
<script src="https://YOUR-FLOBRAIN/v2/widget.js" data-site="SITE_KEY" async></script>
```

Optional `data-lang` (`ar` puts the button on the left), `data-color`, `data-label`,
`data-position`. The script adds a button and, on first click, an iframe to `/p/chat/<siteKey>`.

## Models (`channels` app)

- `ChannelConnection`: kind, label, status (`not_set_up`, `active`, `error`), non-secret `config`,
  `secrets_ciphertext` (one AES-256-GCM JSON blob via `integrations.crypto`, bound to the connection
  and org), `secret_hints` (last 4 characters), `site_key` (website), `serve_team`,
  `serve_customers`, `team_buddy`, `demo`.
- `ChannelLink`: a person linked to a phone or Telegram chat on one connection. Pending rows carry an
  HMAC of the code (never the code), its expiry and nothing else.
- `InboundEvent`: one row per provider message id (unique per connection), with the media reference
  for voice notes.
- `CustomerSettings` (one per org), `CustomerKnowledge` (documents public for customers).
  The knowledge app has no "public for customers" flag, so this list is the only thing the customer
  buddy reads.
- `CustomerConversation` (channel, customer name, masked contact, status `open`/`waiting_human`/
  `resolved`, mode `buddy`/`human`, room, assignee, website token hash) and `CustomerMessage`
  (role `customer`/`buddy`/`staff`/`system`, status `sent`/`draft`/`rejected`/`failed`, citations).

## How messages flow

1. A webhook checks size (256 KB, before reading), the per-connection rate limit, the connection
   (not demo, org active, flag on) and the signature, then stores each message once and processes it
   on the jobs queue (`channels.inbound`), or inline when no worker is deployed.
2. A sender linked on that connection reaches their buddy (`buddies.chat.run_buddy_turn`) with their
   own access. `approve ABC123` / `reject ABC123` decides one of **their own** pending approvals
   through `actions.service.approve/reject`, which re-checks their permission now. A buddy answer that
   proposes an action lists the short codes to reply with. `unlink` unlinks.
3. An unlinked sender who sends a 6-digit code is linked if the code is right, unexpired and unused.
   Five wrong codes per sender per hour, or fifty per connection, lock linking for that hour.
4. Anyone else is a customer when the connection serves customers and `customer_buddy` is on.
   The customer buddy hands off when the customer asks for a person, when a blocked topic appears,
   when no public document matches, when AI is unavailable or private-only, or when the model says
   `ESCALATE`. Hand-off: status `waiting_human`, mode `human`, a post in the hand-off room (as the
   admin who last saved the settings), a notification to the assignee or the room's people who handle
   customers, and a fixed (not AI-written) message telling the customer a person will reply.
5. An AI answer is sent only when the admin turned on auto reply. Otherwise it waits as a draft
   (amber in the inbox) until someone with `customers.reply` approves, edits or discards it. Staff
   replies take over from the buddy and drop old drafts.
6. Voice notes: the media reference is stored and `channels.voice.transcribe_inbound` is called. It
   returns None until W7 is wired (steps in its docstring, using `rooms.voice.transcribe_bytes`), so
   people are asked to type and customers are handed to a person.

## Security notes

- Secrets are never returned, logged or put in fixtures: responses carry `secret_hints` only.
  Telegram puts the bot token in the URL, so outbound errors log only the host.
- Outbound calls go only to `graph.facebook.com` and `api.telegram.org` over HTTPS through
  `platform_api.net.fetch` (public addresses only, pinned connection, no redirects, 10 s timeout).
  Demo connections and `DEMO_MODE` servers never call out.
- Webhook signatures and tokens use `hmac.compare_digest`. Demo connections refuse webhooks.
- The customer buddy's prompt contains only passages from `CustomerKnowledge` documents, quoted as
  data. It never reads rooms, room messages, meetings, or other documents. Citations shown to
  customers carry the title only.
- Website chat: the conversation token is 32 random bytes, returned once, stored as a SHA-256 hash.
  Browser requests must come from an allowed origin, or from FloBrain's own chat page embedded by an
  allowed origin (the page reports the parent from `location.ancestorOrigins` or the referrer).
  CORS headers are added only for the chat endpoints and only for that site's origins
  (`corsheaders` `check_request_enabled` signal). Limits: 30 messages per IP per 10 minutes,
  5 new conversations per IP per hour, 6 messages per conversation per minute, 40 polls per IP per
  minute, plus the anonymous throttle. Override with `CHANNELS_LIMITS` in settings.
- Allowed origins must be `https://` (plain `http://` only for localhost).
- Knowledge selection: an admin can add only documents in rooms they can open; documents chosen by
  someone else in rooms the admin cannot open are counted, not named, and kept on save.
- Every admin and staff action is audited (`channels.*`, `customers.*`); never with secrets.

## Demo

`demo/extras/92_channels.py`: "WhatsApp (demo)", "Telegram (demo)" and "Website chat (demo)" (site key
`demo-nile-labs`, allowed `https://nile-labs.example` and `http://localhost:3000`), all active and
simulated; a "Customer support" room for hand-offs; two public documents (plans and pricing, setup
and support hours); Youssef's Telegram linked; six conversations: one answered after approval, two
with amber drafts, one handed off on request, one blocked topic (refund) taken over by Youssef, one
resolved. Settings, Channels has a "Simulate an inbound message" form (demo only) for a customer
message or your own linked phone. `brain/llm/demo_handlers/channels.py` answers customer questions
from the first source, marked "(Demo answer)", and says `ESCALATE` without sources.

## Before production (needs real credentials)

WhatsApp Cloud API:

1. A Meta Business account that has passed **Meta Business verification**, a Meta app with the
   WhatsApp product, and a phone number registered to a WhatsApp Business account (display name
   approved). Unverified businesses are limited to test numbers and a small daily conversation cap.
2. A **permanent System User access token** with `whatsapp_business_messaging` and
   `whatsapp_business_management` (temporary tokens expire in 24 hours). Copy the phone number ID,
   WABA ID and the app secret (App settings, Basic).
3. Connect in Settings, Channels with a verify token of your choice, then in Meta: WhatsApp,
   Configuration, set the callback URL to the connection's webhook address
   (`{PUBLIC_API_BASE_URL}/api/v2/hooks/whatsapp/{id}`) and the same verify token, and subscribe to the
   `messages` field. Press "Test connection".
4. **24-hour window:** free-form replies (buddy or staff) are allowed only within 24 hours of the
   customer's last message. Later replies need an approved **message template**. FloBrain does not send
   templates yet: such replies are marked "Not sent" (`outside_24h_window`). Building template
   sending means creating templates in WhatsApp Manager and sending `type: "template"` messages.
5. Voice notes: add `lookaside.fbsbx.com` to the allowed hosts when wiring transcription.

Telegram:

1. Create the bot with @BotFather and copy its token. Connect it with a secret token (the form can
   generate one) and press "Test connection" (calls `getMe`).
2. Register the webhook once (from a trusted machine):
   `https://api.telegram.org/bot<token>/setWebhook?url={PUBLIC_API_BASE_URL}/api/v2/hooks/telegram/{id}&secret_token=<secret token>&allowed_updates=["message"]`.
   Only private chats are handled.

Server:

- `CREDENTIALS_ENCRYPTION_KEY` (64 hex chars) must be set, or connecting answers 501.
- `PUBLIC_API_BASE_URL` (shown webhook addresses), `FRONTEND_BASE_URL` (the chat page's origin),
  `NEXT_PUBLIC_API_URL` (frontend), `DRF_NUM_PROXIES` behind a proxy (per-IP limits).
- A shared cache (Redis or Memcached) so rate limits and link lockouts hold across processes; the
  default local-memory cache is per process.
- `JOBS_WORKER_ENABLED` with a `run_jobs` worker so webhooks answer fast; without it messages are
  processed inside the webhook request, which is slower (Meta and Telegram expect a quick 200 and retry otherwise).

## Known limits

- The customer buddy ranks passages by keyword overlap, not embeddings; it is strict by design and
  hands off when nothing matches.
- No WhatsApp templates, media replies, read receipts or typing indicators. Telegram groups are ignored.
- The website chat polls every 4 seconds; there is no push.
- Customer buddy AI calls are not recorded as per-user usage (there is no user); the rate limits
  above bound the cost. They do follow the org's AI policy (private-only orgs hand off).
- The hand-off post needs the settings' last editor to still open the hand-off room; otherwise only
  the notification is sent.
- A portfolio with the slug `chat` would be shadowed by `/p/chat/...`.
