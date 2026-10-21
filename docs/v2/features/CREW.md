# Crew: Flo, specialist buddies and buddy quality (growth round W5)

Flo is a buddy that hands each question to the buddy best placed to answer it, then replies with
"Answered by X". Four specialist templates (Sales, Onboarding Coach, Meeting, Customer) can be added
for the whole org. The Buddy quality page shows how each buddy is doing, with numbers only.

## Flags and permissions

| | |
|---|---|
| Flags | `buddies` (501 when off, like the rest of the buddies API) and `flo_router` (501 when off; Flo is hidden from the buddy list and its threads answer 404) |
| `ai.use` | Talk to Flo, get a routing hint, see templates, rate replies |
| `buddy.manage` | Install a specialist template for the whole org |
| `pulse.view` | Quality numbers for every buddy in the org |
| `ai.usage.view` | Quality numbers for the buddies you can use |

## How Flo routes

1. Candidates are the buddies **you** can use right now (`visible_buddies`), minus Flo and the
   customer persona. With a `room`, buddies limited to other rooms are left out.
2. A small platform call (`DirectProvider`, Pulse routing, budgets and the private-only policy all
   apply) gets the list as quoted data and must answer exactly
   `{"buddy_ids": ["<id>"], "reason": "..."}` (one or two ids). Anything else, including one id that
   is not in the list, is thrown away.
3. If the call is not possible (no provider, private-only org, budget used up) or fails, keyword
   scoring picks the buddy (built-in vocabularies per slug, plus words from each buddy's name and
   description, English and some Arabic). No match: Flo says so and lists buddies to ask.
4. Each chosen buddy answers through `run_buddy_turn` **as you**, in its own thread
   ("Via Flo: ...", reused for the same Flo thread). So its sources are the intersection of what the
   buddy may read and what you can open, its tool calls are proposals in Approvals, and its usage
   counts for that buddy. Flo stores one combined reply: `Answered by <name>` above each answer.

Routing logs (`BuddyRoute`, `BuddyRouteHop`) keep ids, method (`llm`, `keywords`, `none`), candidate
count and timing. They never store the message or the model's reason.

## Specialist templates

Installed as built-in, org-wide buddies (`is_builtin`, approved), off until installed. Installing
again switches a disabled one back on and never overwrites edits.

| Key | Slug | Tools | Sources | Notes |
|---|---|---|---|---|
| `sales` | `sales` | `email.draft`, plus every registered `hubspot.*` tool at install | rooms and docs you can open | Gets your leads (all leads with `commissions.manage`) when `commissions` is on |
| `onboarding` | `onboarding-coach` | `tasks.create` | rooms and docs | Gets your learning paths and progress when `learning` is on |
| `meeting` | `meeting-prep` | `tasks.create`, `email.draft` | rooms, docs, transcripts | Gets your next meetings (rooms you can open), the last meeting summary you can read, and your open tasks |
| `customer` | `customer` | none | none | Public-only persona for the channels app (`buddies.templates_extra.get_template("customer")`); never routed to |

Facts reach the model inside `<workspace_facts>` as data, and only from what the viewer can open
(`buddies.templates_extra.context_for`, one marked hook line in `buddies/chat.py`).

## Feedback and quality

- `BuddyFeedback`: one row per person per reply (`up`/`down`, reason code from `wrong`,
  `incomplete`, `off_topic`, `no_sources`, `too_long`, `unsafe`, `other`, optional note up to 300
  characters). Only replies in your own buddy threads, on buddies you can still use. A rating on a
  Flo reply counts for the buddy that answered (the first one, or `buddy` if you name one of them).
- `BuddyAnswer`: latency and "cited sources" for each reply sent through the buddy chat or Flo.
- Stats per buddy for 7 or 30 whole days: answers, ratings, helpful rate, approvals (proposed,
  approved = approved/executed/failed after approval, rejected, waiting), median latency, share of
  answers with sources, tokens and platform cost (Pulse prices), Flo routing share (real Flo turns,
  not hints), top three "not helpful" reasons, a daily trend and Flo decisions by method.
- The stats endpoint returns numbers, buddy names and reason codes only: no message text, notes,
  reasons from the model or people.

## Endpoints

| Method | Path | |
|---|---|---|
| POST | `/api/v2/orgs/{org}/buddies/route` | `{text, room?}` → `{buddies, reason, method}`; throttled like AI sends |
| GET | `/api/v2/orgs/{org}/buddies/templates` | Templates, installed state, Flo's id, `can_install` |
| POST | `/api/v2/orgs/{org}/buddies/templates/{key}/install` | 201 created, 200 already there |
| GET | `/api/v2/orgs/{org}/buddies/feedback?thread={id}` | Your ratings in one thread |
| POST | `/api/v2/orgs/{org}/buddies/feedback` | `{message, rating, reason?, note?, buddy?}`; 201 new, 200 changed |
| DELETE | `/api/v2/orgs/{org}/buddies/feedback/{message}` | Remove your rating |
| GET | `/api/v2/orgs/{org}/buddies/quality?days=7\|30` | Aggregates |

Additive changes to existing endpoints: thread messages now carry `id`; Flo threads carry
`answered_by` (`{message id: [{id, slug, name}]}`) and the send reply adds `routing`, `answers`;
`GET /buddies/{id}` returns the public card (no prompt) to people who can use but not edit a buddy,
instead of 403, so members can open built-in buddies and Flo.

## Frontend

- `/w/[org]/buddies`: "Ask Flo" card, a Templates section, and a Buddy quality link.
- `/w/[org]/buddies/quality`: totals, a daily trend (answers, rated helpful, rated not helpful; one
  axis, with a table view), a per-buddy table and the "not helpful" reasons. 7 or 30 days.
- `src/components/v2/crew/Feedback.tsx`: `<Feedback orgId messageId initial buddy? />` and
  `useThreadFeedback(orgId, threadId)`. Mount it under each assistant message in the buddy chat
  (`src/app/w/[orgSlug]/buddies/[buddyId]/page.tsx`, not owned by this workstream).

## Demo

`demo/extras/95_crew.py` installs Flo and the four templates, about 70 exchanges over 30 days (a
third through Flo, with routing logs), 60 ratings with reasons, Sales and Meeting proposals (one
waiting in Approvals) and small usage rows tagged so the seeded budgets keep their states.
`brain/llm/demo_handlers/crew.py` answers the routing call by topic (travel, budget, NDA, sign-ups,
launch blockers, sales, new hire, meeting) using only ids in the prompt, and gives labelled sample
answers for the specialists (built from the viewer's facts) and the built-in buddies when no sources
came with the turn.

## Before production

- Nothing needs new credentials. The routing call uses the platform model; consider pointing the
  org's Pulse routing at a small model.
- HubSpot write-back for Sales depends on the connectors workstream registering `hubspot.*` tools
  (they are, as of this round). Install adds the ones registered at that moment; tools registered
  later are added by editing the buddy's tools, since install never overwrites an existing row.

## Known limits

- `@Flo` in rooms is not wired: rooms have no buddy mentions yet. A room composer can call
  `POST /buddies/route` with `room` for a hint, or the room AI can call `buddies.router.flo_turn`.
- Latency and "with sources" are measured only for replies sent through the buddy chat and Flo, not
  scheduled agents. Keyword fallback is simple word overlap.
- A Flo reply with two answers takes one rating, counted for one of the two buddies.
