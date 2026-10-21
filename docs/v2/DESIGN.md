# FloBrain V2 design system: mission control

The brand already speaks starship: the FloLabs Vulcan hand, "Live long and prosper", the Cockpit and Mission Control.
V2 leans into that: a quiet, precise dark interface with one signature, an aurora horizon in the logo's spectrum.

Source of truth for the visuals: the Claude Design canvas "FloBrain V2 design" (website, research, foundations, product boards).

## Tokens (`src/styles/v2-tokens.css`)

| Role | Dark | Use |
|---|---|---|
| `--fb-v2-void` | #05040A | Tools rail, deepest panels |
| `--fb-v2-page` | #08070F | Page |
| `--fb-v2-surface` | #14111F | Cards |
| `--fb-v2-raised` | #1C1829 | Selected and hovered items |
| `--fb-v2-track` | #25203A | Progress tracks |
| `--fb-v2-text` / `-muted` / `-faint` | #EEEBF7 / #A29DB8 / #827D9A | Text |
| `--fb-v2-accent` | #7C6BFF | Primary actions, links, focus |
| `--fb-v2-aurora` | #CC34FF to #7C6BFF to #00D4FF | The signature, used sparingly |
| `--fb-v2-waiting` | #FFB547 | Only "needs a person's approval" |
| `--fb-v2-error` | #FF4D6D | Only blocked, overdue and errors |
| `--fb-v2-success` | #2BD97E | Live, online, done |

Type: Space Grotesk (display and UI), Inter (long reading on the site), JetBrains Mono (timers, scores, counts, metadata, class `v2-mono`), IBM Plex Sans Arabic.

## Rules

- Amber, rose and green each mean one thing. Never use them for decoration or for "series 4".
- Every AI answer shows numbered sources; anything that changes data appears as an amber approval card.
- The aurora horizon (`components/v2/shell/AuroraHorizon.tsx`) appears behind the site hero, the final call to action and sign-in. Nowhere else.
- Each buddy keeps one gradient everywhere (`components/v2/site/content.tsx`).
- Motion: one hero sequence and the cockpit flattening on scroll. Everything respects reduced motion.

## Site (`/v2`)

Pages: `/v2` and `/v2/pricing`, styles in `src/styles/v2-site.css` (scoped under `.v2-site`), components in `components/v2/site`.
Product shots in `public/v2/shots` are 2x renders of the design boards; regenerate them when the cockpit changes.
Pricing on the site is sample data until pricing is decided.
