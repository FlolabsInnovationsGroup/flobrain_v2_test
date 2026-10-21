# Control mapping

How FloBrain covers SOC 2 (Trust Services Criteria) and ISO/IEC 27001:2022 Annex A, for two readers:

1. **FloBrain the company**, working toward SOC 2 Type II and ISO/IEC 27001:2022. The "How FloBrain meets it" column
   says what we have and where; **TO DO** marks evidence we still need. We are not certified.
2. **FloBrain customers**, who use the same automated checks in Settings > Compliance to show their auditors how
   they govern access and AI inside FloBrain.

Control numbers and short names are from the AICPA Trust Services Criteria (2017, points of focus revised 2022) and
ISO/IEC 27001:2022 Annex A. The official criteria and control text are copyrighted and not reproduced; see
`flobrain-core/backend/compliance/catalog.py` for our one-line paraphrases and the sources used to verify numbering.
This file is generated from that catalog (`Automated checks` lists the checks in `compliance/checks.py`).

Status rules in the product: a control passes when every mapped automated check passes, or when a person attests it
with evidence; any failing check makes it a gap and an attestation can't hide that; controls without checks need an
attestation. Readiness is passing / applicable controls.

## Automated checks

| Check | What it reads | Pass when |
|---|---|---|
| `sso_enforced` | `sso.SSOConnection` | SSO is on, enforced, with a verified domain |
| `scim` | `sso.SCIMToken` | an active SCIM token exists (otherwise manual: leavers removed by hand) |
| `owner_mfa` | `sso.SSOConnection` | never automatic: FloBrain has no MFA setting, so this is "not tracked" (manual) |
| `admin_count` | memberships | owners + admins are at most 20% of active members (never fewer than 3 allowed) |
| `dormant_members` | `User.last_active`, memberships | no active member idle for 90 days (configurable) |
| `pending_requests` | `PermissionRequest` | no request waiting more than 14 days (configurable) |
| `leavers_access` | grants, member status | no open grant for paused, terminated, offboarding or graduated people |
| `audit_log` | `AuditEvent` | events in the last 30 days (export: evidence package) |
| `retention_policy` | `privacy.RetentionPolicy` | at least one retention period set |
| `encryption` | settings (presence only) | `CREDENTIALS_ENCRYPTION_KEY` and a non-zero `AES_MASTER_KEY` are set |
| `ai_approvals` | `actions` tool registry, `ToolDefinition`, customer settings | every write tool needs approval (manual when the customer buddy may auto-reply) |
| `ai_data_policy` | `OrgPolicy` | the owner saved a policy |
| `external_agents` | `ExternalAgentServer`, allowlist | every allowed agent is on both allowlists with approved tools (N/A when none) |
| `incidents` | `platform_api.Incident` | incidents recorded and none open over 30 days (manual when none) |
| `backup_export` | `exports.MemoryExport` | an org export succeeded in the last 30 days |
| `data_region` | `OrgPolicy.data_region`, e-invoice residency (soft) | a region is pinned |
| `access_review_recent` | `compliance.AccessReview` | a review completed in the last 90 days (configurable) |
| `policies_acknowledged` | `compliance.PolicyAck` | 90% of due acknowledgements are in (14 days to acknowledge) |
| `trust_center` | `compliance.TrustCenter` | the trust page is published (otherwise manual) |

## SOC 2

| Criterion | Short name | How FloBrain meets it | Automated checks |
|---|---|---|---|
| CC1.1 | Integrity and ethics | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| CC1.2 | Board oversight | Information security policy; leadership review minutes; onboarding checklist | manual |
| CC1.3 | Structure and authority | Owner/admin roles and permission catalog (`organizations/permissions`) | `admin_count` |
| CC1.4 | Competence | Information security policy; leadership review minutes; onboarding checklist | manual |
| CC1.5 | Accountability | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| CC2.1 | Quality information | Append-only audit log (`organizations.AuditEvent`), evidence export | `audit_log` |
| CC2.2 | Internal communication | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| CC2.3 | External communication | Public trust page (`compliance`) | `trust_center` |
| CC3.1 | Clear objectives | Risk list (information security policy, section 5); TO DO: first formal risk assessment | manual |
| CC3.2 | Risk identification | Risk list (information security policy, section 5); TO DO: first formal risk assessment | manual |
| CC3.3 | Fraud risk | Risk list (information security policy, section 5); TO DO: first formal risk assessment | manual |
| CC3.4 | Change impact | Risk list (information security policy, section 5); TO DO: first formal risk assessment | manual |
| CC4.1 | Ongoing evaluations | Quarterly access reviews (`compliance`); Append-only audit log (`organizations.AuditEvent`), evidence export | `access_review_recent`, `audit_log` |
| CC4.2 | Deficiency follow-up | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| CC5.1 | Control activities | Approval-gated AI actions (`actions`), customer buddy drafts | `ai_approvals` |
| CC5.2 | Technology controls | Approval-gated AI actions (`actions`), customer buddy drafts; Org AI and data policy: private-only models, PII redaction (`OrgPolicy`) | `ai_approvals`, `ai_data_policy` |
| CC5.3 | Policies and procedures | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| CC6.1 | Logical access security | SSO (OIDC and SAML, `sso` app) with domain enforcement; owner break-glass; MFA at the identity provider (not tracked in FloBrain); AES-256-GCM for stored secrets (`integrations/crypto.py`), `AES_MASTER_KEY` for memory archives, TLS in transit | `sso_enforced`, `owner_mfa`, `encryption` |
| CC6.2 | User registration and removal | SCIM 2.0 provisioning (`sso/scim.py`); `users.User.last_active`, member status (pause, offboard); Member status changes end sessions; grants revoked; Quarterly access reviews (`compliance`) | `scim`, `dormant_members`, `leavers_access`, `access_review_recent` |
| CC6.3 | Role-based access | Owner/admin roles and permission catalog (`organizations/permissions`); Permission requests and time-limited grants; Quarterly access reviews (`compliance`) | `admin_count`, `pending_requests`, `access_review_recent` |
| CC6.4 | Physical access | See checks; office and device controls: TO DO (MDM, disk encryption evidence) | manual |
| CC6.5 | Asset disposal | Retention policy and daily `apply_retention`; deletion requests (`privacy`) | `retention_policy` |
| CC6.6 | External threats | Outside agent allowlist and approved tool lists (`platform_api/external_agents.py`) | `external_agents` |
| CC6.7 | Data in transit and at rest | AES-256-GCM for stored secrets (`integrations/crypto.py`), `AES_MASTER_KEY` for memory archives, TLS in transit | `encryption` |
| CC6.8 | Malicious software | See checks; office and device controls: TO DO (MDM, disk encryption evidence) | manual |
| CC7.1 | Configuration monitoring | RUNBOOK incident section; Sentry and CloudWatch alerts; dependency audit | manual |
| CC7.2 | Anomaly monitoring | Append-only audit log (`organizations.AuditEvent`), evidence export | `audit_log` |
| CC7.3 | Event evaluation | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| CC7.4 | Incident response | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| CC7.5 | Incident recovery | Incident records and status page (`platform_api.Incident`), RUNBOOK; Org export (`exports`), RDS automated backups | `incidents`, `backup_export` |
| CC8.1 | Change management | Pull requests with review and CI; database migrations; AI actions need approval | `ai_approvals` |
| CC9.1 | Business disruption | Org export (`exports`), RDS automated backups | `backup_export` |
| CC9.2 | Vendors and partners | Outside agent allowlist and approved tool lists (`platform_api/external_agents.py`) | `external_agents` |
| A1.1 | Capacity | Load test baseline (`deploy/loadtest`); Helm autoscaling; RDS backups | manual |
| A1.2 | Backup and recovery infrastructure | Org export (`exports`), RDS automated backups | `backup_export` |
| A1.3 | Recovery testing | Load test baseline (`deploy/loadtest`); Helm autoscaling; RDS backups | manual |
| C1.1 | Identify confidential information | Org AI and data policy: private-only models, PII redaction (`OrgPolicy`); Pinned data region (`OrgPolicy.data_region`), e-invoice residency | `ai_data_policy`, `data_region` |
| C1.2 | Dispose of confidential information | Retention policy and daily `apply_retention`; deletion requests (`privacy`) | `retention_policy` |
| PI1.1 | Processing definitions | API validation; job queue retries and failure alerts | manual |
| PI1.2 | Input controls | API validation; job queue retries and failure alerts | manual |
| PI1.3 | Processing controls | Approval-gated AI actions (`actions`), customer buddy drafts | `ai_approvals` |
| PI1.4 | Output controls | API validation; job queue retries and failure alerts | manual |
| PI1.5 | Stored data | Org export (`exports`), RDS automated backups | `backup_export` |
| P1 | Notice | Public trust page (`compliance`) | `trust_center` |
| P2 | Choice and consent | Privacy center (`privacy` app): what we keep, downloads, deletion requests | manual |
| P3 | Collection | Org AI and data policy: private-only models, PII redaction (`OrgPolicy`) | `ai_data_policy` |
| P4 | Use, retention and disposal | Retention policy and daily `apply_retention`; deletion requests (`privacy`) | `retention_policy` |
| P5 | Access | Privacy center (`privacy` app): what we keep, downloads, deletion requests | manual |
| P6 | Disclosure and notification | Incident records and status page (`platform_api.Incident`), RUNBOOK; Public trust page (`compliance`) | `incidents`, `trust_center` |
| P7 | Quality | Privacy center (`privacy` app): what we keep, downloads, deletion requests | manual |
| P8 | Monitoring and enforcement | Privacy center (`privacy` app): what we keep, downloads, deletion requests | manual |

## ISO/IEC 27001:2022 Annex A

| Control | Short name | How FloBrain meets it | Automated checks |
|---|---|---|---|
| 5.1 | Policies for information security | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| 5.2 | Information security roles and responsibilities | Owner/admin roles and permission catalog (`organizations/permissions`) | `admin_count` |
| 5.3 | Segregation of duties | Owner/admin roles and permission catalog (`organizations/permissions`) | `admin_count` |
| 5.4 | Management responsibilities | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| 5.5 | Contact with authorities | Policy set in `templates/`; owner named per policy | manual |
| 5.6 | Contact with special interest groups | Policy set in `templates/`; owner named per policy | manual |
| 5.7 | Threat intelligence | Dependabot and `pip-audit`/`npm audit`; vendor advisories. TO DO: written process | manual |
| 5.8 | Information security in project management | Policy set in `templates/`; owner named per policy | manual |
| 5.9 | Inventory of information and other associated assets | Policy set in `templates/`; owner named per policy | manual |
| 5.10 | Acceptable use of information and other associated assets | Policy templates, versions and acknowledgements (`compliance`); Approval-gated AI actions (`actions`), customer buddy drafts | `policies_acknowledged`, `ai_approvals` |
| 5.11 | Return of assets | Member status changes end sessions; grants revoked | `leavers_access` |
| 5.12 | Classification of information | Policy set in `templates/`; owner named per policy | manual |
| 5.13 | Labelling of information | Policy set in `templates/`; owner named per policy | manual |
| 5.14 | Information transfer | AES-256-GCM for stored secrets (`integrations/crypto.py`), `AES_MASTER_KEY` for memory archives, TLS in transit | `encryption` |
| 5.15 | Access control | SSO (OIDC and SAML, `sso` app) with domain enforcement; owner break-glass; Quarterly access reviews (`compliance`) | `sso_enforced`, `access_review_recent` |
| 5.16 | Identity management | SSO (OIDC and SAML, `sso` app) with domain enforcement; owner break-glass; SCIM 2.0 provisioning (`sso/scim.py`) | `sso_enforced`, `scim` |
| 5.17 | Authentication information | SSO (OIDC and SAML, `sso` app) with domain enforcement; owner break-glass; MFA at the identity provider (not tracked in FloBrain) | `sso_enforced`, `owner_mfa` |
| 5.18 | Access rights | Quarterly access reviews (`compliance`); Permission requests and time-limited grants; `users.User.last_active`, member status (pause, offboard) | `access_review_recent`, `pending_requests`, `dormant_members` |
| 5.19 | Information security in supplier relationships | Outside agent allowlist and approved tool lists (`platform_api/external_agents.py`) | `external_agents` |
| 5.20 | Addressing information security within supplier agreements | Policy set in `templates/`; owner named per policy | manual |
| 5.21 | Managing information security in the ICT supply chain | Policy set in `templates/`; owner named per policy | manual |
| 5.22 | Monitoring, review and change management of supplier services | Policy set in `templates/`; owner named per policy | manual |
| 5.23 | Information security for use of cloud services | AWS (us-east-1); data region pinned per org; subprocessors on the trust page | `data_region`, `external_agents` |
| 5.24 | Information security incident management planning and preparation | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| 5.25 | Assessment and decision on information security events | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| 5.26 | Response to information security incidents | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| 5.27 | Learning from information security incidents | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| 5.28 | Collection of evidence | Append-only audit log (`organizations.AuditEvent`), evidence export | `audit_log` |
| 5.29 | Information security during disruption | Policy set in `templates/`; owner named per policy | manual |
| 5.30 | ICT readiness for business continuity | Org export (`exports`), RDS automated backups | `backup_export` |
| 5.31 | Legal, statutory, regulatory and contractual requirements | Pinned data region (`OrgPolicy.data_region`), e-invoice residency | `data_region` |
| 5.32 | Intellectual property rights | Policy set in `templates/`; owner named per policy | manual |
| 5.33 | Protection of records | Retention policy and daily `apply_retention`; deletion requests (`privacy`); Append-only audit log (`organizations.AuditEvent`), evidence export | `retention_policy`, `audit_log` |
| 5.34 | Privacy and protection of PII | Org AI and data policy: private-only models, PII redaction (`OrgPolicy`); Retention policy and daily `apply_retention`; deletion requests (`privacy`) | `ai_data_policy`, `retention_policy` |
| 5.35 | Independent review of information security | Policy set in `templates/`; owner named per policy | manual |
| 5.36 | Compliance with policies, rules and standards for information security | Policy templates, versions and acknowledgements (`compliance`); Quarterly access reviews (`compliance`) | `policies_acknowledged`, `access_review_recent` |
| 5.37 | Documented operating procedures | Policy set in `templates/`; owner named per policy | manual |
| 6.1 | Screening | HR process (screening, NDA, onboarding, offboarding): TO DO evidence | manual |
| 6.2 | Terms and conditions of employment | HR process (screening, NDA, onboarding, offboarding): TO DO evidence | manual |
| 6.3 | Information security awareness, education and training | Policy templates, versions and acknowledgements (`compliance`) | `policies_acknowledged` |
| 6.4 | Disciplinary process | HR process (screening, NDA, onboarding, offboarding): TO DO evidence | manual |
| 6.5 | Responsibilities after termination or change of employment | Member status changes end sessions; grants revoked; SCIM 2.0 provisioning (`sso/scim.py`) | `leavers_access`, `scim` |
| 6.6 | Confidentiality or non-disclosure agreements | HR process (screening, NDA, onboarding, offboarding): TO DO evidence | manual |
| 6.7 | Remote working | HR process (screening, NDA, onboarding, offboarding): TO DO evidence | manual |
| 6.8 | Information security event reporting | Incident records and status page (`platform_api.Incident`), RUNBOOK | `incidents` |
| 7.1 | Physical security perimeters | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.2 | Physical entry | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.3 | Securing offices, rooms and facilities | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.4 | Physical security monitoring | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.5 | Protecting against physical and environmental threats | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.6 | Working in secure areas | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.7 | Clear desk and clear screen | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.8 | Equipment siting and protection | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.9 | Security of assets off-premises | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.10 | Storage media | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.11 | Supporting utilities | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.12 | Cabling security | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.13 | Equipment maintenance | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 7.14 | Secure disposal or re-use of equipment | Data centres: AWS (inherited, AWS ISO 27001 certificate). Offices: TO DO | manual |
| 8.1 | User endpoint devices | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.2 | Privileged access rights | Owner/admin roles and permission catalog (`organizations/permissions`); Quarterly access reviews (`compliance`) | `admin_count`, `access_review_recent` |
| 8.3 | Information access restriction | Approval-gated AI actions (`actions`), customer buddy drafts; Permission requests and time-limited grants | `ai_approvals`, `pending_requests` |
| 8.4 | Access to source code | GitHub organization with branch protection; access reviewed with the quarterly review | manual |
| 8.5 | Secure authentication | SSO (OIDC and SAML, `sso` app) with domain enforcement; owner break-glass; MFA at the identity provider (not tracked in FloBrain) | `sso_enforced`, `owner_mfa` |
| 8.6 | Capacity management | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.7 | Protection against malware | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.8 | Management of technical vulnerabilities | `pip-audit`, `npm audit --omit=dev` before release (SECURITY_REVIEW.md) | manual |
| 8.9 | Configuration management | AES-256-GCM for stored secrets (`integrations/crypto.py`), `AES_MASTER_KEY` for memory archives, TLS in transit | `encryption` |
| 8.10 | Information deletion | Retention policy and daily `apply_retention`; deletion requests (`privacy`) | `retention_policy` |
| 8.11 | Data masking | Org AI and data policy: private-only models, PII redaction (`OrgPolicy`) | `ai_data_policy` |
| 8.12 | Data leakage prevention | Org AI and data policy: private-only models, PII redaction (`OrgPolicy`); Outside agent allowlist and approved tool lists (`platform_api/external_agents.py`) | `ai_data_policy`, `external_agents` |
| 8.13 | Information backup | RDS automated backups; restore test each quarter; org export | `backup_export` |
| 8.14 | Redundancy of information processing facilities | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.15 | Logging | Audit log plus application logs (no secrets, no message text) | `audit_log` |
| 8.16 | Monitoring activities | Append-only audit log (`organizations.AuditEvent`), evidence export | `audit_log` |
| 8.17 | Clock synchronization | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.18 | Use of privileged utility programs | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.19 | Installation of software on operational systems | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.20 | Networks security | VPC, security groups, network policies in the Helm chart | manual |
| 8.21 | Security of network services | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.22 | Segregation of networks | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.23 | Web filtering | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.24 | Use of cryptography | AES-256-GCM with bound associated data; TLS; key rotation by key version | `encryption` |
| 8.25 | Secure development life cycle | CONTRIBUTING.md, review on every change, tests in CI | manual |
| 8.26 | Application security requirements | Approval-gated AI actions (`actions`), customer buddy drafts | `ai_approvals` |
| 8.27 | Secure system architecture and engineering principles | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.28 | Secure coding | Linters, type checks, SQL guard, SSRF-safe HTTP client | manual |
| 8.29 | Security testing in development and acceptance | Unit and API tests including permission matrix and security tests | manual |
| 8.30 | Outsourced development | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.31 | Separation of development, test and production environments | Separate local, staging and production settings; demo mode refused in production | manual |
| 8.32 | Change management | Same as SOC 2 CC8.1 | `ai_approvals` |
| 8.33 | Test information | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
| 8.34 | Protection of information systems during audit testing | Engineering standards, CI, `SECURITY_REVIEW.md`, hosting controls | manual |
