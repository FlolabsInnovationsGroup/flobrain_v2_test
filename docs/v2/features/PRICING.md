# Simple pricing: per person or per workspace (growth round M8)

Next to the per-person plans, a plan can be billed per workspace: one price for up to N people
("Studio: up to 25 people, one price"). The billing page shows seats used against the cap, the AI
included for the whole workspace, a switch between plans with a confirmation that lists exactly
what changes, and invoices. The V2 site gets a "Per person | Per workspace" toggle and a team-size
slider that shows which option is cheaper.

**All prices are SAMPLES** until the owners decide (docs/v2/DECISIONS_NEEDED.md Q22). Every API
response that carries a price has `sample: true` (until the setting `BILLING_PRICES_CONFIRMED` is
True) and every screen that shows a price says so.

## Where prices live (one place each side)

| Side | Place | Notes |
|---|---|---|
| Server | `Plan` rows (`billing_plans`) | Written by platform admins (`POST /platform/plans`) or the verified Stripe webhook. The calculator, the switch preview and checkout read rows only. |
| Server, seeding | `billing_v2/sample_plans.py` | Sample Fleet and Studio rows for the demo and sandboxes. Override with the setting `BILLING_SAMPLE_PLANS`. The only server file with price numbers (a test checks the code paths have none). |
| Frontend | `src/components/v2/billing/pricing.ts` (`PRICE_BOOK`) | The site and the slider read it; `content.tsx` derives its price strings from it. |
| Stripe price ids | Environment: `STRIPE_PRICE_<PLAN CODE>_<MONTH or YEAR>` | Or the setting `STRIPE_PRICE_IDS = {"studio": {"month": "price_..", "year": "price_.."}}`. The row's `stripe_price_id` stays as the fallback for its own interval. Never in code. |

Sample numbers: Fleet 12 USD per person a month or 120 a year; Studio 199 USD a month or 1,980 a
year for up to 25 people with 30,000 buddy answers a month for the workspace. Per-seat AI stays in
`growth/allowance.py` (Fleet 1,500 per person).

## The math (same on both sides)

`billing_v2/pricing.py` and `pricing.ts` implement the same rules, and `test_pricing.py` and
`pricing.test.ts` check the same 11 team-size/interval vectors:

- Per seat: unit price x team. Per workspace: one price, unavailable above `included_seats`.
- Yearly price = `price_yearly_cents`, or 12 x monthly when 0. Per month of a yearly price =
  total / 12 rounded half up (`(cents + 6) // 12`).
- In a `tier` (a per-seat and a workspace plan with the same features), the cheaper available paid
  plan wins; a tie goes to per seat. `break_even` is the first team size where the workspace plan
  is cheaper (17 with the samples).

## Flags and permissions

| | |
|---|---|
| Flag | `workspace_pricing`. Off: `/billing` hides per-workspace plans and the `workspace_pricing` block; `/billing/switch` and `/billing/invoices` answer 501; checkout of a workspace plan answers 501. |
| `billing.view` | See billing and invoices (owners and admins, as before) |
| Owner only | Switch plan, checkout, portal (as before) |
| Public calculator | Off by default: on with the setting or env `WORKSPACE_PRICING_PUBLIC=True`, or in demo mode. 30 requests a minute per IP. |

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/orgs/{org}/billing` | As before, plus (flag on) `workspace_pricing`: `seat_status` {unit, limit, used, policy, upgrade_to}, `ai` {basis, total, per_seat, used}, `price` (current plan described), `invoices`, `sample`. Plan rows gain `billing_unit`, `included_seats`, `overage_policy`, `ai_allowance_per_workspace`, `price_monthly_cents`, `price_yearly_cents`, `tier`, `sample`. |
| POST | `/orgs/{org}/billing/switch` | `{plan, interval, seats?, confirm?}`. Without `confirm`: a preview `{from, to, changes[], proration}`. With `confirm`: Stripe mode updates the Stripe subscription (`proration_behavior=create_prorations`) and answers `pending` (our row changes when the verified webhook arrives), or opens a checkout when there is no Stripe subscription yet; demo mode applies it; otherwise 501. |
| GET | `/orgs/{org}/billing/invoices` | Invoices copied from Stripe by the webhook (or the demo's samples). |
| POST | `/orgs/{org}/billing/checkout` | Additive: `interval` (month/year); workspace plans use quantity 1 and must fit the people already in the org (409 `seat_limit`). |
| GET | `/pricing/calculator?team=17&interval=year` | Public, rate limited. Every public plan's cost for that team and interval, `comparisons` per tier, `cheaper`, `sample`. |

Switch validation: unknown plan 404; interval not month/year or not sold 400; per seat below the
people already in the org 400; per workspace when the org has more people than the cap 409
`seat_limit`; same plan, interval and seats 400 `no_change`.

## Models (migration `billing_v2/0003_workspace_pricing`)

- `Plan`: `billing_unit` (`per_seat` | `per_workspace`), `included_seats`, `overage_policy`
  (`block` | `prompt_upgrade`, both block; the second also suggests the per-person plan of the
  same tier), `ai_allowance_per_workspace`, `price_yearly_cents`, `tier`.
- `Subscription.interval` (month | year).
- `Invoice`: a copy of a Stripe invoice (number, status, amount, period, `hosted_url` kept only for
  `invoice.stripe.com` / `pay.stripe.com`), or a demo sample.

## Seat cap

`billing_v2.entitlements.seat_blocked()` was already the single check for every path that adds
or reactivates a member: register/invite (`organizations/views_directory.py`), reactivation
(`MemberDetailView.patch`), SCIM provisioning (`sso/scim.py`) and HR intake
(`integrations_hr/views.py`). `seat_limit()` now returns the plan's `included_seats` whenever the
org is on an active per-workspace plan, even with `BILLING_ENFORCE_ENTITLEMENTS` off, because
"up to N people" is the plan's promise. No path charges for extra people. `seat_error(org, seats)`
builds the clearer error body (plan name, cap, `policy`, `upgrade`) for those hooks to return.

## Webhook

Still verified (HMAC-SHA256, constant-time compare, timestamp tolerance, idempotent by event id).
Additions: the price id maps to a plan and interval through the env mapping; workspace plans keep
`seats = included_seats` (Stripe quantity is 1); `invoice.finalized`, `invoice.paid`,
`invoice.payment_failed` and `invoice.voided` upsert an `Invoice` for a subscription we know.

## Demo

`demo/extras/a8_pricing.py`: sample Fleet and Studio plans, the demo org on Studio (monthly) with
8 of 25 seats (adds demo people on the demo domain when the core seed has fewer), and four sample
invoices (three paid, this month's upcoming), amounts computed from the plan rows. The demo switch
applies at once with "no payment was taken".

## Before production

- Owners decide prices, plan names (Crew/Fleet/Studio/Mission are placeholders) and caps (Q22).
- Create the Stripe products and prices; set `STRIPE_PRICE_<CODE>_<INTERVAL>`, `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`; subscribe the webhook to `customer.subscription.*`, `checkout.session.completed`
  and `invoice.*`. Turn on the Customer Portal's invoice history.
- Set `BILLING_PRICES_CONFIRMED=True` and update `PRICE_BOOK` (`PRICES_ARE_SAMPLE = false`) together.
- Terms, refund and AI usage policies must exist before live payments (Legal, Q22).

## Known limits

- The switch preview shows the new recurring price; the exact prorated amount is Stripe's and
  appears on the next invoice (no upcoming-invoice call yet).
- `growth/allowance.py` (the AI seat meter) still counts per seat for every plan; the billing page
  uses its own workspace meter for workspace plans. See "Hooks in other files".
- The public calculator compares within a tier; plans without a pair are listed but not compared.

## Hooks in other files (not changed by this workstream)

1. `growth/allowance.py` `summary()`, so `/ai-allowance` and `AiSeatMeter` agree on workspace plans:

   ```python
   from billing_v2.entitlements import ai_allowance

   workspace_total = ai_allowance(org)  # None unless on an active per-workspace plan
   included = workspace_total if workspace_total is not None else per_seat * seats
   # and add to data: "basis": "per_workspace" if workspace_total is not None else "per_seat"
   ```

2. The seat-limit responses in `organizations/views_directory.py` (two places), `sso/scim.py` and
   `integrations_hr/views.py` can return the clearer body:

   ```python
   from billing_v2.entitlements import seat_blocked, seat_error

   seats = seat_blocked(org, email=email)
   if seats is not None:
       return Response(seat_error(org, seats), status=409)
   ```

3. `flobrain/settings.py` (optional, the code reads the env when the setting is absent):
   `WORKSPACE_PRICING_PUBLIC = os.environ.get("WORKSPACE_PRICING_PUBLIC", "False") == "True"` and
   `BILLING_PRICES_CONFIRMED = os.environ.get("BILLING_PRICES_CONFIRMED", "False") == "True"`.
