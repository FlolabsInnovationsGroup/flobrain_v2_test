# Phase 17 plan: enterprise and commercial readiness

Branch `v2/phase-7-ai` continues (local, not pushed). Sources: `PLAN.md` Phase 17, spec 6.19 and 7, Decisions 8, 20, 41, 49, 50; Q21, Q22, Q25, Q37 defaults (nothing hard-coded). New billing tables are additive; the old `customer_billing`, `payment_history`, `group_billing`, `group_payment_history` stay untouched (Q37).

## 17a — Org policy and sovereign mode

`OrgPolicy` (`inference_scope` `external_allowed|private_only`, `pii_redaction` `off|external_only|always`, `data_region`). `GET/PUT /orgs/{org}/policy` (owner). One gate, `brain.llm.policy.check_ai(org, target)`, called before every model call: in `private_only` only hosts on `AI_SELF_HOSTED_HOSTS` are allowed, the legacy multimodal host is refused, customer BYOK keys to external hosts are refused and set to `disabled` when the policy changes, external agents are refused. Features that cannot run privately return "unavailable". PII redaction stays a documented interface (Presidio is a separate service, Q25) and is not enabled here.

## 17b — Plans and entitlements, Stripe

`billing.Plan` (entitlements JSON of flags and limits), `Subscription`, `UsageInvoiceLine`. `effective_flag` gains the plan: when `BILLING_ENFORCE_ENTITLEMENTS` is on and the org has a subscription, a flag is on only if the plan includes it. Plans are written by platform admins or the verified Stripe webhook (`POST /api/v2/billing/stripe/webhook`, signature with timestamp tolerance, idempotent by event id). `GET /orgs/{org}/billing` shows plan, seats, usage at cost (BYOK at zero). No checkout UI in this phase.

## 17c — SSO (OIDC first)

`sso.SSOConnection` per org: issuer, client id, encrypted client secret, verified domains (DNS TXT `flobrain-verify=<token>`), `enforced` (the owner keeps a break-glass password login). Authorization-code flow with PKCE, `state` and `nonce`, ID-token checks (issuer, audience, expiry, nonce, signature via the issuer's JWKS, `email_verified`). An assertion signs in only existing or SCIM-provisioned members of that org whose email domain is verified for it. SAML 2.0 is an interface with "Not configured" until a library and an IdP test tenant exist (TECH_DEBT).

## 17d — SCIM 2.0

`SCIMToken` (hash). `/scim/v2/Users` and `/scim/v2/Groups` (list, get, create, patch, delete, filter `userName eq`). Groups map to teams by an explicit mapping. SCIM never grants owner, admin or lead; users without a mapped team are `pending`; `active=false` pauses the membership and revokes the user's personal access tokens.

## 17e — Memory export, marketplace, platform console

`POST /orgs/{org}/exports/memory` (owner) builds a zip on the worker: documents and room messages from team/project rooms with sources, as JSON + Markdown. It excludes direct and group rooms, AI threads and mentor notes. In-org marketplace for buddies and templates with admin approval before install. Platform console endpoints for `is_platform_admin` (orgs, plans, flags; impersonation needs a reason, is time-limited, visible to the customer and audited).

## 17f — Sovereign package

`deploy/` with a Helm chart skeleton and a docker-compose "open models only" profile (`AI_PROVIDER_BACKEND=direct` to a self-hosted vLLM, `EMBEDDINGS_BACKEND=http` to a self-hosted BGE-M3, `inference_scope=private_only`), plus a runbook. No cloud change from this branch.
