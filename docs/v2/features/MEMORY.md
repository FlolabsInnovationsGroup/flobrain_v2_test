# Buddy memory (growth round M4)

Buddies remember short, useful facts about a person ("Prefers short answers", "Leads the Android launch") or a team ("Code freeze starts two days before every release"), so people don't repeat themselves. People see, edit and delete everything; nothing sensitive is stored.

## Flags and permissions

| What | Needs |
|---|---|
| Everything | flag `buddy_memory` (off by default, on in the demo). Off: endpoints return 501 and buddies neither use nor save memory; chat commands go to the model as ordinary text. |
| Your own memory, pause, chat commands | `ai.use` |
| Team memory (edit) and the org rules | `memory.manage` (owners and admins by default) |
| Reading your teams' memory | `ai.use` and being in the team |

Personal memory is only ever readable by its person. Admins can't read it (the rules page shows counts only).

## How it works

1. **Capture.** After a buddy turn (surface `buddy` only, not scheduled agents, not turns on a customer key), if the message looks like the person said something about themselves (`I`, `my`, `we`, Arabic, Turkish, French, Portuguese equivalents), one cheap call to the platform model (`[flo:memory-capture]`, Pulse routing, AI policy, platform budget, usage recorded on the thread) proposes 0 to 3 facts as strict JSON. Bad output stores nothing.
2. **Filter.** Every candidate passes `buddy_memory.filters.check` before anything is written: `platform_api.pii` (always at least the regex detector: emails, phones, cards with Luhn, IBANs, national ids) plus category rules for health, religion, politics, sexual orientation and relationships, money and salary, government ids and immigration, card and bank details, precise home address, children, passwords and keys, ethnicity and criminal records. Text is normalised (NFKC, accents and Arabic diacritics folded, zero-width removed) and checked again with tricks undone ("s a l a r y", "p4ssport"). Blocked candidates are dropped silently. The same filter runs on manual, team, edit and "remember that" paths (manual paths answer 400 `sensitive` without echoing the text).
3. **Ask before saving** (default on). Candidates become pending suggestions. The buddy's reply ends with `Should I remember this: “…”? Reply yes or no.` A plain yes or no in that same thread answers it without a model call; the Memory page also lists them. With the rule off, facts are saved directly and the reply says so.
4. **Use.** The hook adds at most 8 personal and 4 team memories (pinned first, then word overlap with the message, then recent use) to the system prompt as a quoted `<memory>` block titled "What you know about this person (may be outdated)", with `<`/`>` neutralised. Only the person's own memories and teams they belong to (a team-shared buddy only sees its own team). Pending, expired and blocked-category memories are never used. `last_used_at` is updated.
5. **Commands** (deterministic, before the model): "remember that …" (confirmed; sensitive text refused with an explanation), "forget …" (deletes the person's matching memories; when nothing matches, the message goes to the buddy as usual, so "forget the last answer" still works), "forget everything", "what do you remember about me". English, Arabic, Turkish, French, Portuguese. Questions ending in "?" are never commands.
6. **Delete is real.** Every delete removes the row. A keyed HMAC of the deleted or declined text (not the text) is kept for 180 days so the same fact isn't suggested again; it is removed with the person.

## Org rules (`memory.manage`, audited without memory text)

On/off, ask before saving, retention (30 days to 2 years, or until deleted; default 180), blocked categories (from preference, work context, project, people, other; existing memories in a newly blocked category are deleted), team memory on/off. Changing retention recomputes every expiry and purges what is now too old. Suggestions lapse after 14 days.

## Endpoints

- `GET /orgs/{org}/memory` summary: rules, `me.paused`, counts, categories, `never_stored`, `can_manage`, your teams
- `GET /orgs/{org}/memory/items?q=&category=&status=active|pending|all&scope=person|team`
- `POST /orgs/{org}/memory/items` `{text, category}`; `DELETE /orgs/{org}/memory/items` (all of yours)
- `PATCH|DELETE /orgs/{org}/memory/items/{id}` (`text`, `category`, `pinned`); another person's id is 404
- `POST /orgs/{org}/memory/items/{id}/confirm`, `/reject`
- `PUT /orgs/{org}/memory/me` `{paused}`: buddies neither save nor use your memory while paused
- `GET|PUT /orgs/{org}/memory/rules`; `GET /orgs/{org}/memory/teams`
- `GET|POST /orgs/{org}/memory/teams/{team}/items`; `PATCH|DELETE /orgs/{org}/memory/teams/{team}/items/{id}`

Audit actions: `memory.item.create|update|delete|delete_all|confirm|reject`, `memory.pause`, `memory.team.create|update|delete`, `memory.rules.update`. Payloads hold ids, categories, field names and counts, never the text.

## Models (`buddy_memory/0001_initial`)

- `MemoryItem`: org, scope (person|team), user or team (check constraint), text (300), category, source (buddy|chat|manual), source_message, created_by_buddy, created_by, confirmed, pinned, status (active|pending), asked_chat, digest, last_used_at, expires_at.
- `MemorySettings` (one per org), `MemoryPreference` (pause per person per org), `MemoryDeclined` (hash only).

## Privacy

- Account deletion: personal memories cascade with the user.
- Leaving an org (membership deleted, or status terminated, offboarding, graduated) and an approved deletion request (`DeletionRequest.status = done`) erase the person's memories, declined hashes and pause in that org, through signals connected by this app (privacy and organizations untouched).
- Export and inventory: `privacy.services` has no registry, so the lead adds (in `build_export`'s `parts` and `inventory`'s `data`):

```python
from buddy_memory.privacy import count_for, export_rows
parts["buddy_memories.json"] = export_rows(user)          # build_export
"buddy_memories": count_for(user, org),                     # inventory()["data"]
```

  `buddy_memory.tests.PrivacyTests.test_privacy_export_includes_memories` runs once that line exists (skipped until then).

## Scheduling

`python manage.py tick_buddy_memory` deletes expired memories and old declined hashes. Run it daily (Helm cronjob or compose ticker, like `apply_retention`). The demo ticker runs it by itself. Expired rows are also hidden from every read until the purge runs.

## Demo

`demo/extras/a4_memory.py`: default rules, 8 memories for Youssef (member), 2 pending suggestions, 3 team memories (Engineering 2, Design 1). The demo model's handler (`brain/llm/demo_handlers/memory.py`) proposes facts for typical sentences ("I prefer short answers", "I'm leading the iOS beta", "I work with Sara on …") and nothing for sensitive ones. In a demo chat, "I'm leading the iOS beta. What is blocking it?" ends with the "Should I remember this?" question; answer "yes".

## Before production

- Nothing external. The capture call uses the platform model like other buddy calls (and costs a small extra call per qualifying message). Orgs on private-only inference need a self-hosted model or capture is skipped.
- Consider setting `PII_DETECTOR` to a real detector (Presidio adapter); the filter uses it automatically.

## Known limits

- The sensitivity filter is keyword and pattern based. It is deliberately strict (some harmless facts like "votes for Rust" are refused) and can still miss unusual phrasing in languages other than English, Arabic, Turkish, French and Portuguese. The capture prompt also tells the model not to propose these categories.
- The "Should I remember this?" question and command replies are in English.
- In a Flo thread, commands run inside each buddy Flo picks (deduplicated), and a yes or no only answers a question asked in the same thread.
- Relevance is word overlap, not embeddings.
