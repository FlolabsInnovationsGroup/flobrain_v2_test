import { getLocale, t } from "@/i18n";

export type Access = {
  org: { id: string; slug: string; name: string; demo: boolean };
  user_id: string;
  org_role: "owner" | "admin" | "member" | null;
  is_platform_admin: boolean;
  leads_teams: string[];
  permissions: string[];
  flags: Record<string, boolean>;
  demo_role: string | null;
};

export function has(access: Access | null, perm: string): boolean {
  return !!access && access.permissions.includes(perm);
}

export function flag(access: Access | null, key: string): boolean {
  return !!access && !!access.flags[key];
}

export function isLead(access: Access | null): boolean {
  return !!access && access.leads_teams.length > 0;
}

export function roleKey(access: Access | null): "owner" | "admin" | "lead" | "member" | "" {
  if (!access) return "";
  if (access.org_role === "owner") return "owner";
  if (access.org_role === "admin") return "admin";
  if (isLead(access)) return "lead";
  return "member";
}

export function roleLabel(access: Access | null): string {
  const key = roleKey(access);
  return key ? t(getLocale(), `demo.roles.${key}`) : "";
}

export type NavItem = { href: string; label: string; icon: string; badge?: "approvals" };
export type NavGroup = { label: string; items: NavItem[] };

/** The workspace navigation for this person. Only shows what they can actually use. */
export function navFor(slug: string, access: Access | null): NavGroup[] {
  const w = (path: string) => `/w/${slug}${path}`;
  const groups: NavGroup[] = [
    {
      label: "nav.work",
      items: [
        { href: w(""), label: "nav.home", icon: "home" },
        { href: w("/tasks"), label: "nav.tasks", icon: "kanban" },
        { href: w("/time"), label: "nav.time", icon: "clock" },
        { href: w("/calendar"), label: "nav.calendar", icon: "calendar" },
        ...(has(access, "mission.view") ? [{ href: w("/mission-control"), label: "nav.missionControl", icon: "kanban" }] : []),
        { href: w("/insights"), label: "nav.insights", icon: "activity" },
      ],
    },
    {
      label: "nav.talk",
      items: [
        ...(has(access, "room.view") ? [{ href: w("/rooms"), label: "nav.rooms", icon: "users" }] : []),
        { href: w("/notifications"), label: "nav.inbox", icon: "inbox" },
        { href: w("/search"), label: "nav.search", icon: "search" },
        { href: w("/directory"), label: "nav.people", icon: "users" },
      ],
    },
  ];
  const ai: NavItem[] = [];
  if (flag(access, "memory_search") && has(access, "knowledge.ask")) ai.push({ href: w("/ask"), label: "nav.ask", icon: "sparkles" });
  if (flag(access, "buddies") && has(access, "ai.use")) ai.push({ href: w("/buddies"), label: "nav.buddies", icon: "bot" });
  if (flag(access, "ai_actions")) ai.push({ href: w("/approvals"), label: "nav.approvals", icon: "check", badge: "approvals" });
  if (flag(access, "scheduled_agents") && has(access, "ai.use")) ai.push({ href: w("/agents"), label: "nav.agents", icon: "timer" });
  if (flag(access, "auto_reports") && (isLead(access) || has(access, "report.generate"))) ai.push({ href: w("/reports"), label: "nav.reports", icon: "file" });
  if (flag(access, "pulse") && (has(access, "pulse.view") || isLead(access))) ai.push({ href: w("/pulse"), label: "nav.pulse", icon: "activity" });
  if (flag(access, "automations") && has(access, "automations.use")) ai.push({ href: w("/automations"), label: "Automations", icon: "zap" });
  if (flag(access, "data_buddy") && has(access, "data.use")) ai.push({ href: w("/data"), label: "Data", icon: "chart" });
  if (flag(access, "buddies") && flag(access, "flo_router") && (has(access, "pulse.view") || has(access, "ai.usage.view"))) ai.push({ href: w("/buddies/quality"), label: "Buddy quality", icon: "gauge" });
  if (ai.length) groups.push({ label: "nav.ai", items: ai });
  const create: NavItem[] = [];
  if (flag(access, "content_studio") && has(access, "content.use")) create.push({ href: w("/studio"), label: "nav.studio", icon: "clapper" });
  if (flag(access, "buddies") || flag(access, "content_studio")) create.push({ href: w("/marketplace"), label: "nav.marketplace", icon: "store" });
  if (flag(access, "learning")) create.push({ href: w("/learning"), label: "nav.learning", icon: "graduation" });
  if (flag(access, "commissions")) create.push({ href: w("/commissions"), label: "nav.commissions", icon: "handshake" });
  if (flag(access, "academy")) create.push({ href: w("/academy"), label: "Academy", icon: "graduation" });
  if (flag(access, "packs") && has(access, "packs.install")) create.push({ href: w("/packs"), label: "Industry packs", icon: "layers" });
  if (create.length) groups.push({ label: "nav.create", items: create });
  const org: NavItem[] = [];
  if (has(access, "org.members.manage") || has(access, "grants.create") || has(access, "permission_requests.create")) org.push({ href: w("/settings/access"), label: "nav.access", icon: "shield" });
  if (has(access, "team.manage") || has(access, "project.manage") || isLead(access)) org.push({ href: w("/settings/teams"), label: "Teams and projects", icon: "layers" });
  if (has(access, "audit.view")) org.push({ href: w("/settings/audit"), label: "Audit log", icon: "scroll" });
  if (access) org.push({ href: w("/settings/feedback"), label: access.org_role === "owner" || access.org_role === "admin" ? "Feedback and analytics" : "Your reports", icon: "message" });
  if (flag(access, "customer_buddy") && (has(access, "customers.view") || has(access, "customers.reply"))) org.push({ href: w("/customers"), label: "Customers", icon: "message" });
  if (flag(access, "channels") && (has(access, "channels.manage") || has(access, "ai.use"))) org.push({ href: w("/settings/channels"), label: "Channels", icon: "phone" });
  if (flag(access, "integrations") || (flag(access, "write_integrations") && (has(access, "integrations.act") || has(access, "integrations.manage")))) org.push({ href: w("/integrations"), label: "nav.integrations", icon: "plug" });
  org.push({ href: w("/settings/notifications"), label: "nav.notifications", icon: "bell" });
  org.push({ href: w("/privacy"), label: "nav.privacy", icon: "eye" });
  org.push({ href: w("/settings/developer"), label: "nav.developer", icon: "code" });
  if (has(access, "policy.manage") || has(access, "org.view")) org.push({ href: w("/settings/ai-policy"), label: "nav.aiPolicy", icon: "lock" });
  if (flag(access, "byok") && has(access, "ai.use")) org.push({ href: w("/settings/ai-keys"), label: "nav.aiKeys", icon: "key" });
  if (has(access, "ai.usage.view")) org.push({ href: w("/settings/usage"), label: "nav.usage", icon: "activity" });
  if (flag(access, "budgets") && has(access, "budget.view")) org.push({ href: w("/settings/budgets"), label: "nav.budgets", icon: "card" });
  if (has(access, "billing.view")) org.push({ href: w("/settings/billing"), label: "nav.billing", icon: "card" });
  if (has(access, "sso.manage")) org.push({ href: w("/settings/sso"), label: "nav.sso", icon: "key" });
  if (has(access, "org.members.manage")) org.push({ href: w("/settings/retention"), label: "nav.retention", icon: "timer" });
  if (has(access, "exports.memory")) org.push({ href: w("/settings/export"), label: "nav.export", icon: "download" });
  if (has(access, "audit.view")) org.push({ href: w("/settings/support-access"), label: "nav.supportAccess", icon: "eye" });
  if (flag(access, "external_agents") && has(access, "ai.use")) org.push({ href: w("/settings/external-agents"), label: "nav.externalAgents", icon: "bot" });
  if ((flag(access, "status_page") && has(access, "incidents.manage")) || access?.is_platform_admin) org.push({ href: w("/settings/incidents"), label: "nav.incidents", icon: "activity" });
  groups.push({ label: "nav.organization", items: org });
  if (access?.is_platform_admin) {
    groups.push({ label: "nav.platform", items: [{ href: w("/platform"), label: "nav.console", icon: "server" }] });
  }
  if (access?.demo_role) {
    groups.push({ label: "nav.demo", items: [{ href: w("/tour"), label: "nav.tour", icon: "map" }] });
  }
  return groups;
}
