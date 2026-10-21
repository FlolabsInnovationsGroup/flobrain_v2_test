export type NotificationRow = {
  id: string;
  kind: string;
  payload?: Record<string, unknown>;
  read_at?: string | null;
};

export function unreadNotifications(rows: NotificationRow[]): NotificationRow[] {
  return rows.filter((row) => !row.read_at);
}

export function notificationsEmpty(rows: NotificationRow[]): boolean {
  return rows.length === 0;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");
const SAFE_LINK = /^[a-z0-9][a-z0-9/_-]{0,120}$/;

type Described = { text: string; vars?: Record<string, string>; link: string | null };

/**
 * Plain words for a notification (an English sentence with {placeholders}, translated at render),
 * and an in-workspace link when it has one (never another site).
 */
export function describe(row: NotificationRow): Described {
  const p = row.payload ?? {};
  const room = str(p.room) ? `rooms/${str(p.room)}` : null;
  const map: Record<string, () => Described> = {
    room_message: () => ({ text: "New message in a room you're in", link: room }),
    mention: () => (str(p.by) ? { text: "{by} mentioned you", vars: { by: str(p.by) }, link: room } : { text: "Someone mentioned you", link: room }),
    direct_message: () => (str(p.by) ? { text: "New message from {by}", vars: { by: str(p.by) }, link: room } : { text: "New direct message", link: room }),
    announcement: () =>
      str(p.room_name) ? { text: "New announcement in {room}", vars: { room: str(p.room_name) }, link: room } : { text: "New announcement in a room you're in", link: room },
    "task.assigned": () => ({ text: "You were assigned “{title}”", vars: { title: str(p.title) }, link: "tasks" }),
    "task.blocked": () => ({ text: "“{title}” is blocked", vars: { title: str(p.title) }, link: "tasks" }),
    "task.due_soon": () => ({ text: "“{title}” is due tomorrow", vars: { title: str(p.title) }, link: "tasks" }),
    "task.overdue": () => ({ text: "“{title}” is overdue", vars: { title: str(p.title) }, link: "tasks" }),
    "meeting.summary_ready": () => ({ text: "Meeting summary ready: “{title}”", vars: { title: str(p.title) }, link: SAFE_LINK.test(str(p.link)) ? str(p.link) : null }),
    publish_failed: () => ({ text: "A scheduled social post couldn't be published", link: SAFE_LINK.test(str(p.link)) ? str(p.link) : "studio" }),
    render_finished: () => ({ text: "Your video “{title}” is rendered", vars: { title: str(p.title) }, link: SAFE_LINK.test(str(p.link)) ? str(p.link) : "studio" }),
    pulse_alert: () => (str(p.text) ? { text: "{text}", vars: { text: str(p.text) }, link: "pulse" } : { text: "A Pulse alert fired", link: "pulse" }),
    budget_alert: () =>
      str(p.scope) && typeof p.percent === "number"
        ? { text: "AI budget for {scope} is at {percent}%", vars: { scope: str(p.scope), percent: String(p.percent) }, link: "settings/budgets" }
        : { text: "An AI budget is nearly used up", link: "settings/budgets" },
    buddy_share_request: (): Described => {
      if (!str(p.by) || !str(p.name)) return { text: "A buddy share request is waiting", link: "buddies/requests" };
      if (p.target === "team" && str(p.team)) {
        return { text: "{by} asked to share {name} with {team}", vars: { by: str(p.by), name: str(p.name), team: str(p.team) }, link: "buddies/requests" };
      }
      return { text: "{by} asked to share {name} with the organization", vars: { by: str(p.by), name: str(p.name) }, link: "buddies/requests" };
    },
    buddy_share_decided: () => ({
      text: p.outcome === "approved" ? "Your request to share {name} was approved" : "Your request to share {name} was rejected",
      vars: { name: str(p.name) || "a buddy" },
      link: str(p.buddy) ? `buddies/${str(p.buddy)}` : "buddies",
    }),
    "automation.notice": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "automations" }),
    "automation.daily_brief": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "tasks" }),
    "automation.nudge": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "tasks" }),
    "customer.message": () => ({ text: "{text}", vars: { text: str(p.text) }, link: "customers" }),
    "customer.escalated": () => ({ text: "{text}", vars: { text: str(p.text) }, link: "customers" }),
    "data.report": () => ({ text: "{text}", vars: { text: str(p.title) || str(p.text) }, link: "data" }),
    "compliance.review_assigned": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "settings/compliance" }),
    "compliance.review_reminder": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "settings/compliance" }),
    "compliance.policy_published": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "settings/compliance" }),
    "compliance.trust_request": () => ({ text: "{text}", vars: { text: str(p.text) || str(p.title) }, link: "settings/compliance" }),
    "academy.badge": () => ({ text: "{text}", vars: { text: str(p.title) }, link: "academy" }),
    "impersonation.started": () => ({ text: "Support access started by {admin}", vars: { admin: str(p.admin) }, link: "settings/support-access" }),
    deletion_request: () =>
      str(p.by) ? { text: "{by} asked to delete their data", vars: { by: str(p.by) }, link: "settings/retention" } : { text: "Someone asked to delete their data", link: "settings/retention" },
    "access.requested": () => ({ text: "{by} asked for access: {label}", vars: { by: str(p.by), label: str(p.label) || str(p.perm_key) }, link: "settings/access" }),
    "access.decided": () => ({
      text: p.outcome === "approved" ? "Your access request was approved: {label}" : "Your access request was turned down: {label}",
      vars: { label: str(p.label) || str(p.perm_key) },
      link: "settings/access",
    }),
    "access.granted": () => ({ text: "You were given access: {label}", vars: { label: str(p.label) || str(p.perm_key) }, link: "settings/access" }),
    deletion_request_decided: () => ({
      text: p.outcome === "done" ? "Your deletion request was completed" : p.outcome === "rejected" ? "Your deletion request was rejected" : "Your deletion request was decided",
      link: "privacy",
    }),
  };
  const out = map[row.kind]?.() ?? (str(p.text) ? { text: "{text}", vars: { text: str(p.text) }, link: null } : { text: "{kind}", vars: { kind: row.kind.replace(/[._]/g, " ") }, link: null });
  const link = str(p.link) || out.link;
  return { ...out, link: link && SAFE_LINK.test(link) ? link : null };
}

/** The English sentence with its values filled in (for tests and plain-text use). */
export function describeText(row: NotificationRow): string {
  const { text, vars } = describe(row);
  return text.replace(/\{(\w+)\}/g, (m, k: string) => vars?.[k] ?? m);
}
