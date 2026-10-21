# Review: Phases 15–16 and the 10–13 fixes

An independent agent reviewed `46e5f52e..1abf5ff1` (connectors, meeting bot, privacy center, seat cap, platform onboarding, and the fixes from `REVIEW_PHASES_10_13.md`) and confirmed five findings with throwaway tests. Everything below is fixed, with a regression test where marked.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | A new org's owner was created pending, so nobody could ever sign in to it | The onboarded owner is active; an existing account gets a notice email (test) |
| 2 | High | Slugs like `signin` or `sso` were accepted (their workspace could never open), and one-letter slugs passed | Every static `/w/` page is reserved; 3–50 characters enforced (test) |
| 3 | Medium | The seat cap could be bypassed by reactivating a terminated member, through SCIM or the HR webhook, or by two requests at once | One `seat_blocked` check that locks the org row, used by invite, reactivation, SCIM create and the HR webhook (test) |
| 4 | Medium | Erasure left cached message translations holding the text | Translations are deleted and `updated_at` is set (test) |
| 5 | Medium | "Keep my personal insights to myself" and the product-analytics consent were saved but not enforced | Consent is enforced: product events are not recorded when it's off (test). The personal-insights switch is hidden until a personal-insight screen exists (TECH_DEBT) |
| 6 | Low/Medium | A request filed by a member who later became owner could erase the owner; platform staff from outside the org could file or decide requests; two admins could both decide | Owner re-checked at decision time, only active members of the org file or decide, the request row is locked (test) |
| 7 | Low/Medium | `safeNext` could be fooled by `/w/..//evil.com` style paths | Parsed with `URL`, same origin and a `/w/` path required after normalisation (website test) |
| 8 | Low | A demo seat could still get a password through first-login | 403 for demo accounts (test) |
| 9 | Low | Connector items accepted any URL scheme; a non-dict `pull_request` crashed GitHub sync; managers saw names of private rooms they aren't in | Only `https://` links are stored, the shape is checked, other rooms' names are hidden |
| Minor | Low | Meeting summaries outlived their transcripts under retention; racing privacy saves or onboarding could 500 | Summaries follow transcripts; `get_or_create` for settings; `IntegrityError` → 409 |

## Follow-up review of `42b1b1ec`

| Finding | Fix |
|---|---|
| The "keep my insights to myself" switch disappeared | Intended: hidden until a screen honours it (TECH_DEBT); the setting stays stored |
| Onboarding or inviting an existing user stored with capitals created a second account | `register_member` matches the email case-insensitively (test) |
| Deletion notifications lost who asked and the outcome | The payload carries `by` and `outcome`; the text says completed or rejected |
| Billing counted seats differently from the cap | `seats_used` uses the same statuses as the cap |
| SCIM said `tooMany` for an existing member of a full org | "Already a member" is checked first |
| Small UI gaps: Arabic comma in English, SSO page not right-to-left, agent presets untranslated, summaries missing from retention, private room name text from the backend | Fixed; the backend sends `room_hidden` and the page words it |
| Arabic wording | "Blocked" → عالقة, won/lost leads → مكسوب/مفقود, one word for Marketplace (المتجر الداخلي), and others |
