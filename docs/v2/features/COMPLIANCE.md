# Compliance: SOC 2 and ISO 27001 readiness (M7)

Settings > Compliance helps an org get ready for SOC 2 and ISO/IEC 27001:2022 and show its auditor how it governs
access and AI inside FloBrain. It shows **readiness**, never certification. FloBrain's own policy templates and the
control mapping are in `docs/v2/compliance/`.

## Flags and permissions

| | |
|---|---|
| Flag | `compliance` (off by default, on in the demo). Off: every org endpoint answers 501 `not_implemented`, the public trust page answers 404 |
| `compliance.view` | Overview, controls, checks, reviews, evidence list, policies, trust settings and requests (owners and admins by default) |
| `compliance.manage` | Attest controls, settings, start and run access reviews, build and download evidence, install and publish policies, edit and publish the trust page, handle requests |
| Any active member | `me`, `my-policies` (read and acknowledge), `my-reviews` and the items they were asked to review |

## What it does

1. **Control catalog** (`compliance/catalog.py`): SOC 2 (CC1 to CC9 with their 33 criteria, A1, C1, PI1, P1 to P8) and
   ISO/IEC 27001:2022 Annex A (93 controls: 37 organizational, 8 people, 14 physical, 34 technological). Numbers and
   short names only, with our own one-line paraphrases; sources are cited in the file.
2. **Automated checks** (`compliance/checks.py`, 19 checks) read real data: SSO enforced, SCIM, MFA (reported as
   "not tracked": FloBrain has no MFA setting), admin count, dormant members, old permission requests, leavers'
   grants, audit log, retention, encryption keys (presence only), AI approvals, AI and data policy, outside agent
   allowlist, incidents, org export, data region (also reads e-invoice residency softly when that app has a field
   for it), recent access review, policy acknowledgements, trust page. Each result is pass, fail (gap), manual or
   not applicable, with evidence pointers into the workspace. A check that crashes becomes manual; it never hides
   the others.
3. **Control status** (`compliance/readiness.py`): mapped checks decide; a failing check is a gap and an attestation
   can't hide it; controls without checks need a person's attestation (evidence note, optional https link, owner) or
   "not applicable". Readiness is passing / applicable.
4. **Access reviews** (`compliance/reviews.py`): items are each active member's role (with teams and last sign-in),
   every open permission grant, personal write connections (Google, Microsoft and the rest) and custom buddies
   shared with a team or the org. Reviewers: the lead of a team the person is in, otherwise admins; nobody reviews
   themselves; the owner's access can only be kept. Decisions: keep, revoke, change (role admin/member; grant end
   date 7, 30, 90 or 180 days). An owner or admin's decision is applied at once through the same paths FloBrain
   already uses (`perm.revoke`, `member.role`, `member.status` → paused, `integration.write.disconnect`, buddy made
   private); a lead's revoke or change waits for an admin to apply it. Reminders by notification (and push) on
   demand, at most once an hour, and daily from `compliance_tick` when a review is due within 3 days. A review
   completes only when every item is decided and applied; the report is JSON or CSV.
5. **Evidence packages** (`compliance/evidence.py`): a ZIP with `controls.json/.csv`, `checks.json`,
   `audit_log.csv` for the period, `access_reviews.json`, `access_review_items.csv`, `policies.json`,
   `policy_acknowledgements.csv`, `config_snapshot.json`, `README.txt` and `manifest.json` (size and SHA-256 of every
   file). Stored in private storage (`content_studio.storage`, key `compliance/<org>/<package>/evidence.zip`),
   downloadable through the API by `compliance.manage` only (audited), deleted after 7 days. At most 10 a day per org,
   periods up to 400 days, built synchronously.
6. **Policies** (`compliance/policies.py`): seven templates (information security, access control, acceptable use
   with AI use, incident response, data retention, vendor management, business continuity) installed as Documents in
   a "Security policies" room (active members are added so they can read them). Publishing snapshots the document as
   a numbered version with its SHA-256 and asks every member to acknowledge it. Acknowledgements are per version;
   members have 14 days.
7. **Trust center** (`compliance/trust.py`): `/trust/<slug>` shows only the sections the org turned on: security
   overview, control readiness (percentages by framework and area only: no control names, evidence or people),
   subprocessors (editable, https links only), data location, documents on request. Off until published. The request
   form validates, has a honeypot, is limited to 3 an hour per visitor and 30 a day per org, notifies admins in the
   app and by email (and the contact email), and never sends documents automatically. FloBrain's own trust content
   (`FLOBRAIN_EXAMPLE`) is offered as a starting point and used by the demo.

## Endpoints

Org endpoints are under `/api/v2/orgs/{org}/compliance/`.

| Method and path | Who | What |
|---|---|---|
| `GET me` | member | `can_view`, `can_manage`, open review items, policies to read |
| `GET overview` | view | Readiness by framework and area, all check results, open review, last package |
| `GET/PATCH settings` | view/manage | Frameworks shown, dormant days (30 to 365), request age (1 to 90), review interval (30 to 365) |
| `GET controls?framework=&status=&group=&q=` | view | Controls with status, source, checks and attestation |
| `PUT/DELETE controls/{framework}/{id}/attestation` | manage | `{status: pass|fail|not_applicable, note, evidence_url?, owner?}` |
| `GET/POST reviews` | view/manage | List; start `{name?, period?, reviewer_mode: team_leads|admins, due_days}` (one open at a time) |
| `GET reviews/{id}[?mine=1]` | view or reviewer | Review with items (reviewers see only theirs) |
| `POST reviews/{id}/items/{item}/decision` | reviewer or manage | `{decision: keep|revoke|change, change_to?, note?}` |
| `POST reviews/{id}/remind|apply|complete|cancel` | manage | Reminders, apply waiting changes, complete, cancel |
| `GET reviews/{id}/report[?export=csv]` | view | Completion report |
| `GET my-reviews` | member | Open items this person may decide |
| `GET/POST evidence` | view/manage | List; build `{start, end}` (YYYY-MM-DD; default the last 90 days) |
| `GET evidence/{id}/download` | manage | The ZIP (410 after 7 days) |
| `GET policy-templates` | view | Templates and whether installed |
| `GET/POST policies` | view/manage | List; install `{templates: [...], publish?}` |
| `GET policies/{id}` | view | Current text, versions, who has not acknowledged |
| `POST policies/{id}/publish` | manage | New version from the document (no change: 200, `changed: false`) |
| `POST policies/{id}/acknowledge` | member | `{version}` (409 when a newer version exists) |
| `GET my-policies` | member | Published policies with this person's acknowledgement |
| `GET/PUT trust` | view/manage | Settings, FloBrain's example, a preview; `published: true` makes the page public |
| `GET trust/requests`, `PATCH trust/requests/{id}` | view/manage | Requests; mark `sent` or `declined` |

Public (signed out): `GET /api/v2/public/trust/{slug}` and `POST /api/v2/public/trust/{slug}/requests`
(`{name, email, company?, documents?, message?, website?}`; always 202 when accepted). No shared URL file changed:
these live in `compliance/urls.py`, already included under `/api/v2/`.

Website: `/w/[org]/settings/compliance` (tabs: Overview, Controls, Access reviews, Evidence, Policies, Trust center,
For you; members without `compliance.view` see only For you) and the public `/trust/[slug]`.

## Models

`ComplianceProfile`, `ControlAttestation`, `AccessReview`, `AccessReviewItem`, `EvidencePackage`, `Policy`,
`PolicyVersion`, `PolicyAck`, `TrustCenter`, `TrustRequest`. Migration `compliance/0001_initial`.

## Security notes

- No secrets anywhere: the encryption check and the config snapshot say only whether keys are set; the snapshot
  leaves out SSO client ids, IdP metadata and tokens; audit payload fields whose names look secret (secret, token,
  password, api key, private key, dsn, ciphertext, credential, authorization, cookie, signature) and values that look
  like key material (PEM private keys, `sk-`, Slack, GitHub and AWS key shapes) are replaced with `[removed]`. A test
  plants real-looking secrets and scans every file in the ZIP.
- CSV cells that start with `=`, `+`, `-` or `@` are prefixed with `'` so spreadsheets do not run them.
- Evidence files are private: served only through the API after a permission check, `Cache-Control: no-store`.
- Every change is audited (`compliance.*`, plus the underlying `perm.revoke`, `member.role`, `member.status`,
  `integration.write.disconnect`, `buddy.unshare`).
- The trust page hides itself when the flag is off or the org is inactive; it caches the readiness numbers for
  10 minutes; visitor addresses are stored only as a salted hash.
- Nothing in this app calls the network. Email goes through Django's `send_mail` (SMTP settings).

## Demo

`demo/extras/a7_compliance.py`: a recent org export and a pinned data region; a completed Q2 review and an open Q4
review with some decisions (one lead revoke waiting for an admin); two published policies everyone acknowledged and
a draft; three controls marked not applicable and enough attestations (notes start with "Demo:") for about 70% of
controls to pass, with real gaps left (SSO not enforced, the open review, and keys missing on a local server); an
evidence package when storage is available; a published trust page at `/trust/demo` using FloBrain's example
content, and two requests.

## Before production

- Confirm `FLOBRAIN_EXAMPLE` (subprocessors, data location, wording) against contracts before any real use.
- SMTP settings for request emails; `CONTENT_STORAGE=s3` and the private bucket for evidence packages.
- Schedule `python manage.py compliance_tick` daily (reminders and package expiry) in Helm and compose.
- Nav: members find policies and review items through notifications that link to the For you tab; see the report
  for an optional nav change.

## Known limits

- MFA is not tracked (FloBrain accounts have no MFA setting); it is reported as manual.
- Evidence packages are built in the request (fine for the 50 000-row audit cap); a very large org may want a job.
- Control names in the product are in English (standard terms); check titles and all screen copy are translated.
- The catalog covers Annex A controls and TSC criteria, not ISO clauses 4 to 10 or SOC 2 system descriptions.
- Changing a team lead after a review starts does not reassign that review's items.
