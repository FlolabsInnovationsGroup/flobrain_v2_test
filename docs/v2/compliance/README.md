# FloBrain compliance pack

FloBrain is **working toward** SOC 2 Type II and ISO/IEC 27001:2022. We are **not certified**. Nothing in this folder
or in the product may say otherwise until an accredited auditor has issued a report or certificate.

## What is here

| File | For |
|---|---|
| `CONTROL_MAPPING.md` | Every SOC 2 criterion and ISO/IEC 27001:2022 Annex A control, how FloBrain meets it, and which automated check gives evidence. Generated from `flobrain-core/backend/compliance/catalog.py`. |
| `templates/information-security.md` | Top-level policy: principles, roles, risk, exceptions |
| `templates/access-control.md` | Accounts, SSO and MFA, granting, quarterly reviews, leavers, AI and outside agents |
| `templates/acceptable-use.md` | Company systems, customer data, and AI use (approved tools, approvals, no secrets in prompts) |
| `templates/incident-response.md` | Reporting, severity, steps, customer and regulator notice, lessons |
| `templates/data-retention.md` | Periods per data type, people's requests, legal holds, backups |
| `templates/vendor-management.md` | Vendor checks, AI providers, outside agents, subprocessors |
| `templates/business-continuity.md` | Recovery targets, backups and exports, tests |

The templates use placeholders (`{{ORG_NAME}}`, `{{POLICY_OWNER}}`, `{{EFFECTIVE_DATE}}`, retention days) that FloBrain
fills when an org installs them from Settings > Compliance > Policies. A copy lives in
`flobrain-core/backend/compliance/policy_templates/` so the backend image ships them; a test keeps both copies equal.
Edit them here and copy the file over.

## For FloBrain the company (audience A)

Use FloBrain on our own workspace the way a customer would:

1. Install all seven templates, adapt them (owners, real retention periods, recovery targets), publish, and get every
   member's acknowledgement.
2. Run an access review each quarter (team leads review their teams).
3. Build an evidence package at the end of each quarter and keep it in the audit folder (packages expire in
   FloBrain after 7 days by design).
4. Close the **TO DO** items in `CONTROL_MAPPING.md`: formal risk assessment, HR evidence (screening, NDAs),
   device management, data classification, office security, a written vulnerability process.
5. Before using the trust page publicly, confirm the subprocessor list (`compliance/trust.py`, `FLOBRAIN_EXAMPLE`)
   against signed contracts and DPAs, and add the email provider once chosen.
6. SOC 2 Type II needs a period of operating evidence (usually 3 to 12 months) after a readiness assessment. ISO
   27001 also needs the ISMS clauses 4 to 10 (scope, risk treatment, Statement of Applicability, internal audit,
   management review), which these controls do not cover on their own.

## For customers (audience B)

Settings > Compliance shows customers which of their controls FloBrain can prove (access, AI governance,
logging, retention, encryption) and lets them attest the rest, run access reviews, collect evidence packages and
publish a trust page. It covers how they govern access and AI **inside FloBrain**, not their whole company.
