/** Check titles in the reader's language. The server sends English; keys are stable. */
export function checkTitle(tr: (text: string) => string, key: string, fallback: string): string {
  switch (key) {
    case "sso_enforced":
      return tr("Single sign-on is enforced");
    case "scim":
      return tr("SCIM provisioning is on");
    case "owner_mfa":
      return tr("Owners and admins use MFA");
    case "admin_count":
      return tr("Few people hold admin rights");
    case "dormant_members":
      return tr("No dormant members");
    case "pending_requests":
      return tr("No old permission requests");
    case "leavers_access":
      return tr("People who left hold no extra access");
    case "audit_log":
      return tr("Audit log is on and exportable");
    case "retention_policy":
      return tr("Retention policy is set");
    case "encryption":
      return tr("Encryption keys are configured");
    case "ai_approvals":
      return tr("AI actions need a person's approval");
    case "ai_data_policy":
      return tr("AI and data policy is saved");
    case "external_agents":
      return tr("Outside AI agents are allowlisted");
    case "incidents":
      return tr("Incidents are recorded");
    case "backup_export":
      return tr("An org export ran recently");
    case "data_region":
      return tr("Data region is pinned");
    case "access_review_recent":
      return tr("Access review done in the last 90 days");
    case "policies_acknowledged":
      return tr("Members acknowledged the policies");
    case "trust_center":
      return tr("Trust page is published");
    default:
      return fallback;
  }
}
