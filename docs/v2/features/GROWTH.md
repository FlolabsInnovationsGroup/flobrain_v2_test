# Academy, industry packs, marketplace ratings and AI per seat (W6)

Growth round workstream W6. Backend app `growth` (plus additive changes in `marketplace`), frontend
routes `/w/[org]/academy` and `/w/[org]/packs`, components in `src/components/v2/growth/`, phrase area
`academy`.

## What it does

**Academy** (flag `academy`, every member). Eight short lessons about using FloBrain well: write good
asks, build a buddy, approvals, workflows, the data buddy, meetings to tasks, Arabic and English,
security basics. Each lesson has a markdown body in English and Arabic, a "Try it" link into the
product, and a 2 or 3 question check (pass mark: two thirds). Progress is per person; passing every
check awards the Academy badge once (audited, with a notification). The **coach** answers questions
about using FloBrain from the lesson text and facts about the asking person only, and suggests the
next lesson (the first open lesson about a feature that is on for them and that they haven't used yet).

**Industry packs** (flag `packs`, permission `packs.install`, admins by default). Three declarative
manifests in `growth/packs.py`: Education, Small business, Agency. Each lists rooms, buddies, starter
knowledge documents, workflows and time tracking tags. The preview says exactly what an install creates
and what is skipped because a feature is missing ("Needs Workflows", "Needs Channels"). Install is
idempotent: a second install creates only items that were skipped before and are now possible.
Uninstall deletes only objects nobody changed or used since; the rest is kept and listed with the reason.

**Marketplace** (existing flags). Ratings of 1 to 5 stars with an optional review of up to 500
characters, one per person per listing (all versions share it), only by people who installed it and
never by its author. Listings carry `rating {average, count}`, `my_rating` and `verified`. Version
history comes from the existing lineage. "Verified by FloBrain" is set by platform staff only.

**AI included per seat** (flag `budgets`, permission `ai.usage.view`). The plan's included buddy
answers per seat per month, seats, use this month, a straight-line month-end projection, your own use,
and use per person for owners and admins. **Sample numbers** until pricing is confirmed.

## Endpoints (all under `/api/v2`)

| Method | Path | Notes |
|---|---|---|
| GET | `orgs/{org}/academy` | lessons, my progress, my badge |
| GET | `orgs/{org}/academy/lessons/{key}` | body, body_ar, check without answers |
| POST | `orgs/{org}/academy/lessons/{key}/progress` | `{step: read or tried}` |
| POST | `orgs/{org}/academy/lessons/{key}/check` | `{answers: [int]}`; answers revealed only once passed |
| POST | `orgs/{org}/academy/coach` | `{question, lesson?}`; needs `ai.use`; 30 a day per person |
| GET | `orgs/{org}/packs` | packs and install state |
| GET | `orgs/{org}/packs/{key}/preview` | items with `action` create, skip, installed, removed and `needs` |
| POST | `orgs/{org}/packs/{key}/install` | `{confirm: true}`; 201 first time, 200 after |
| POST | `orgs/{org}/packs/{key}/uninstall` | `{confirm: true}`; returns `removed` and `kept` |
| GET | `orgs/{org}/ai-allowance` | meter data; `people` only for owners and admins |
| GET, POST, DELETE | `orgs/{org}/marketplace/{id}/ratings` | reviews; rate; remove my rating |
| GET | `orgs/{org}/marketplace/{id}/versions` | version history (POST is the existing "new version") |
| POST | `orgs/{org}/marketplace/{id}/verified` | `{verified: bool}`, platform staff only |

A flag that is off answers 501 `not_implemented` (the convention of every V2 feature; the frontend
shows "switched off"). A missing permission answers 403. Unknown lesson or pack: 404.

## Models and migrations

- `growth.LessonProgress` (org, user, lesson, read_at, tried_at, attempts, best_score, completed_at)
- `growth.AcademyBadge` (one per person per org)
- `growth.InstalledPack` (pack, status, items with model, id and fingerprint, skipped, kept); one active install per pack and org
- `marketplace.Rating` (lineage, user, stars 1 to 5 with a DB check, review, version); unique per lineage and user
- `marketplace.Listing.verified`, `verified_by`, `verified_at`

Migrations: `growth/migrations/0001_initial.py`, `marketplace/migrations/0005_ratings_verified.py`.

## Security notes

- The coach prompt (marker `[flo:academy-coach]`) contains only shipped lesson text, the asker's
  effective flags, counts filtered on the asker (`user=`), the asker's lesson progress and the names of
  installed packs. No documents, messages, names or numbers about other people. Lesson text and the
  question are quoted (`knowledge.prompting.quote`) and the system prompt says they are data. Calls
  go through `DirectProvider` (Pulse routing), the org budget check and the private-only policy check,
  and are recorded as usage (surface `learning`).
- Pack buddies are validated with `buddies.services.clean_definition` against the installer's own
  access; actions the installer doesn't hold are dropped. They are created org-wide and approved by the
  installer, who holds `packs.install` and saw the exact definition in the preview (audited as
  `packs.install`).
- Pack workflows are validated with the Workflows app's own `clean_workflow` (rooms must be ones the
  installer can use), created **switched off** with no schedule, and the invoice and client report
  workflows include a `wait_for_approval` step. Nothing runs, posts or sends until someone turns it on.
- Uninstall never deletes something that changed (field fingerprint) or that anything else points at
  (messages, other documents, members other than the installer, chats, pins, time entries, workflow
  runs). Tags that existed before the pack are never claimed.
- Ratings: installers only, never the author, range and length checked, audited. The verified mark is
  checked on `is_platform_admin` directly, because org owners hold every permission key.
- Optional apps (`automations`, `buddies.templates_extra`) are looked up at call time
  (`importlib`, `apps.get_model`); the module never imports them at import time (tested).
- The allowance meter keeps the usage page's privacy promise: people who keep their insights personal
  are one combined row for admins.

## Demo

`demo/extras/96_growth.py`: Layla finished every lesson (badge), Youssef is halfway, Omar and Sara
started; the Small business pack is installed by Omar (its invoice workflow is created switched off);
an approved, verified "Weekly report writer" listing with two versions, three installs and three
reviews; this month's AI answers for every demo person (budget caps are scaled so the demo budgets keep
their percentages and demo AI is not blocked). `brain/llm/demo_handlers/growth.py` answers the coach in
English or Arabic and says it is demo output.

## Before production

- **Pricing**: the per-seat allowances in `growth/allowance.py` (`DEFAULT_PER_SEAT`, e.g. Fleet 1,500
  buddy answers per seat) are placeholders (DECISIONS_NEEDED Q22). Set `GROWTH_AI_ALLOWANCE` in Django
  settings and `"sample": false` once prices are approved.
- The meter is gated on the `budgets` flag; a dedicated flag may be preferable.
- No external credentials are needed for this workstream.

## Known limits

- Lessons and packs are shipped in code; there is no editor. Pack labels are translated in the
  frontend phrase files; created objects (room names, documents, buddy prompts) are in English.
- Pack buddies use a specialist template from `buddies.templates_extra` when one exists for the key
  (`sales`, `customer`), else the fallback in the manifest.
- The projection is a straight line from the start of the month.
- The coach keeps no history; each question is answered on its own.
- `AiSeatMeter` is exported but not mounted on an existing page (see the W6 report).
