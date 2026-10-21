# Review: Phase 17 (enterprise and commercial readiness)

Date: 2026-10-20. Built by Claude in the container. Reviewed by a separate agent that had not seen the work being written (`git diff b45800ff..a407b550`), which proved the High findings and three Medium ones with throwaway tests. Then fixed and re-tested here. Branch `v2/phase-7-ai`, local only, not pushed.

## Findings and fixes

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | 17c SSO | Enforced SSO was only checked on V2 sign-in. V1 `POST /api/auth/signin/` still returned tokens that worked on V2, and refresh tokens from before enforcement kept working. | High | **Fixed**. V1 sign-in returns 403 `sso_required` (same rule as V2, owner break-glass kept). Turning enforcement on ends existing sessions of the covered members (the password-change cut-off), and V1 refresh now honours that cut-off as V2 already did. |
| 2 | 17c SSO | An admin could point the org's SSO at their own IdP (enabled and verified domains carried over) and sign in as the owner, or as a platform admin who is a member. | High | **Fixed**. `sso.manage` is owner-only and not grantable. Changing the issuer or client id switches SSO and enforcement off until the owner turns them on again. SSO never signs in a platform admin. The audit row records the old and new issuer. |
| 3 | 17d SCIM | SCIM could attach any existing FloBrain account (any domain) to the org as pending/paused, which blocked that person's V2 sign-in, and could squat new accounts. | Medium | **Fixed**. `userName` must be in one of the org's verified SSO domains. Concurrent creates return 409, not 500. |
| 4 | 17d SCIM | A paused admin could reactivate themselves with a SCIM token they had minted; tokens outlived their creator. | Medium | **Fixed**. SCIM reactivates only plain members that SCIM itself paused or created (`status_reason = scim`), never admins, leads or people paused in FloBrain. A token works only while its creator is still the active owner. Revocation is audited. A SCIM pause also ends the person's sessions. Paused people are not put back on teams through groups. |
| 5 | 17e export | "Owner-only" export (and `policy.manage`) could be granted to an admin through a grant or a permission request. | Medium | **Fixed**. `OWNER_ONLY_KEYS` (`exports.memory`, `policy.manage`, `sso.manage`): held only by a real active owner, outside admin defaults, refused by both grant and permission-request validation. |
| 6 | 17e/Q42 | The platform-admin bypass let staff export an org, mint SCIM tokens and reconfigure SSO without impersonation or notice. | Medium | **Fixed** for these keys: the owner-only check runs before the platform-admin bypass, so staff need a real owner seat. The general bypass stays an open decision (Q42). |
| 7 | 17f sovereign | V1 chat ignored `AI_FORCE_PRIVATE_ONLY` and the default multimodal URL is an external IP; the API container has outbound access. | Medium | **Fixed**. V1 send returns 409 `private_only` when the install is forced private (no change for the hosted deploy). `MULTIMODAL_SERVICE_URL` is empty in `env.example` and the Helm config. The compose file documents why the API keeps outbound access (IdP, webhooks) and how to restrict it. |
| 8 | 17a | Admins could change the AI policy (plan says owner). | Low | **Fixed** by #5. |
| 9 | 17d | SCIM PUT `{"active": "false"}` activated the user. | Low | **Fixed**. Strict boolean parsing for PUT and PATCH; anything else is 400. |
| 10 | 17 | 500s on bad bodies: SCIM `name` as a string, JSON arrays in marketplace, console and SSO domain endpoints. | Low | **Fixed**. All parse safely to 400. |
| 11 | 17b Stripe | Unpaid async checkouts became active; ignored events were recorded and never re-applied; a late update could revive a canceled subscription. | Low | **Fixed**. Checkout needs `payment_status` paid (or no payment required). Ignored events are rolled back so retries apply. `last_event_at` drops older events, and canceled is final (a new checkout starts a new subscription). The plan in checkout metadata is still trusted while no server-side checkout endpoint exists (TECH_DEBT). |
| 12 | 7h/17b | Indexing (embedding spend) ignored the plan. | Low | **Fixed**. `org_indexing_enabled` also checks the plan entitlement. |
| 13 | 17c | Login CSRF: someone else's callback link or `/w/sso?code=` link could sign a victim into the attacker's account. | Low | **Fixed**. `/sso/start` requires a `client_nonce` the browser keeps (sessionStorage); the one-time code is redeemable only with the same nonce. Frontend contract changed (CHANGELOG). |
| 14 | 17e | Read-only impersonation still triggered paid translation and moved the person's read marker. | Low | **Fixed**. Both are skipped or refused under a support token. |
| 15 | 17f | Helm: no ingress policy, no container hardening, egress left out IdP/storage, migrate hook ran before the ConfigMap. Compose: `DB_PASS` on the `psql` command line. Local export files were never purged. | Low | **Fixed**. Ingress `NetworkPolicy`, `allowPrivilegeEscalation: false`, read-only root with an `emptyDir` `/tmp`, all capabilities dropped, `extraEgress` for IdP/storage, migrate as `post-install,pre-upgrade`. `PGPASSWORD` in compose. Local delete in storage, with a path check. |

## Checked and fine (reviewer)

- Impersonation: token type keeps it out of V1, refresh and middleware; every request re-checks the live session, admin status and password change, the target's active membership; GET only, own org path only; refused on `/platform/*`; end and expiry take effect at once; no export links.
- OIDC: PKCE S256, single-use state claimed atomically, nonce, JWKS with RS256/ES256 only, iss/aud/exp, `email_verified`, verified domain, no account creation, single-use 2-minute code, SSRF-safe client, secret never returned.
- Domain verification per org; a domain verified elsewhere is refused.
- SCIM org isolation, owner protected, never grants owner/admin/lead, only plain members removed from teams.
- Stripe signature: HMAC, constant-time, tolerance, once per event id under concurrency.
- Marketplace: frozen snapshot, no self-approval, installer access re-checked, room lists stripped.
- `check_ai` before every V2 model call; plaintext hosts only for operator-set base URLs.
- Export content: team/project rooms, non-deleted messages, their documents only.

## Left open

- Q42: the general platform-admin bypass (outside the owner-only keys).
- Stripe checkout plan from metadata (safe while checkout sessions are created server-side only).
- Helm chart not yet linted (tool not reachable from this environment).

## Proof

- SQLite and PostgreSQL 16: **424** tests pass (was 413; +11 regression tests for the findings above).
- `makemigrations --check`: no changes (`sso/0002_browser_binding`, `billing_v2/0002_subscription_last_event`).
- `docker compose config` on the sovereign profile: valid.
