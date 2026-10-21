/** Rules shared by the directory, profile, access, audit and feedback screens (no React here). */

export type TeamRole = { id: string; name: string; role: "lead" | "member"; is_active?: boolean };
export type Skill = { id: number; name: string; confirmed: boolean };

export type Member = {
  id: string;
  username: string | null;
  avatar_url?: string | null;
  org_role: "owner" | "admin" | "member";
  employment_status: string;
  presence: string;
  email?: string;
  phone?: string | null;
  about_me?: string | null;
  timezone?: string | null;
  discord_handle?: string | null;
  linkedin_url?: string | null;
  teams?: string[];
  team_roles?: TeamRole[];
  is_lead?: boolean;
  skills?: Skill[];
  status_reason?: string | null;
  projects?: { id: string; name: string; status: string; is_lead: boolean }[];
  can?: { change_status: boolean; change_role: boolean; confirm_skills: boolean };
};

export type DirectoryFilters = { q: string; status: string; team: string; role: string; skill: string; page: number };

export const EMPTY_FILTERS: DirectoryFilters = { q: "", status: "all", team: "", role: "", skill: "", page: 1 };

/** Decision 6 filters, in the order the directory shows them. */
export const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "online", label: "Online" },
  { value: "away", label: "Away" },
  { value: "on_leave", label: "Leave" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

export const EMPLOYMENT_STATUSES = ["active", "paused", "graduated", "terminated", "offboarding"] as const;

/** Query parameters for ``GET /members``; empty filters are left out. */
export function memberQuery(f: DirectoryFilters): Record<string, string> {
  const out: Record<string, string> = { ordering: "name", page: String(Math.max(1, f.page)) };
  const q = f.q.trim();
  if (q) out.q = q;
  if (f.status && f.status !== "all") out.status = f.status;
  if (f.team) out.team = f.team;
  if (f.role) out.role = f.role;
  if (f.skill.trim()) out.skill = f.skill.trim();
  return out;
}

export function pageCount(count: number, pageSize = 20): number {
  return Math.max(1, Math.ceil(count / pageSize));
}

export function displayName(m: { username?: string | null; email?: string; id: string }): string {
  return m.username || m.email || m.id;
}

export function statusTone(status: string): "good" | "waiting" | "bad" | "neutral" {
  if (status === "active") return "good";
  if (status === "pending" || status === "paused" || status === "offboarding") return "waiting";
  if (status === "terminated") return "bad";
  return "neutral";
}

/** Status sentences, in English (translated at render). */
export const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  pending: "Pending",
  paused: "Paused",
  graduated: "Graduated",
  terminated: "Terminated",
  offboarding: "Offboarding",
};

export const PRESENCE_LABEL: Record<string, string> = {
  online: "Online",
  away: "Away",
  on_leave: "On leave",
  offline: "Offline",
};

/** Setting someone to anything but active stops them signing in (Decision 7). */
export function statusChangeWarning(next: string): string {
  if (next === "active") return "They can sign in again and get new tasks and messages.";
  return "They can't sign in, get new tasks or new direct messages. Their past work stays visible to leads.";
}

/** E.164 like the backend: a plus, a country code, 8 to 15 digits. Null when it doesn't fit. */
export function normalizePhone(raw: string): string | null {
  let value = raw.replace(/[\s().-]/g, "");
  if (value.startsWith("00")) value = `+${value.slice(2)}`;
  return /^\+[1-9]\d{7,14}$/.test(value) ? value : null;
}

export const GRANT_DURATIONS: { label: string; days: number | null }[] = [
  { label: "For a day", days: 1 },
  { label: "For a week", days: 7 },
  { label: "For a month", days: 30 },
  { label: "For three months", days: 90 },
  { label: "No end date", days: null },
];

export type Grant = {
  id: string;
  perm_key: string;
  label?: string;
  scope_type: string;
  scope_name?: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  active?: boolean;
  expired?: boolean;
  grantee_user?: { id: string; username: string } | null;
  granted_by_user?: { id: string; username: string } | null;
};

export type GrantState = "active" | "expiring" | "expired" | "revoked";

/** "expiring" = ends within two days, so admins can renew it in time. */
export function grantState(g: Grant, now = Date.now()): GrantState {
  if (g.revoked_at) return "revoked";
  if (g.expires_at) {
    const end = Date.parse(g.expires_at);
    if (end <= now) return "expired";
    if (end - now <= 2 * 86400000) return "expiring";
  }
  return "active";
}

export type CatalogRow = { key: string; label: string; matrix: string; grantable?: boolean };

/** What a person may still ask for: grantable keys they don't already hold. */
export function requestable(catalog: CatalogRow[], held: string[]): CatalogRow[] {
  const mine = new Set(held);
  return catalog.filter((row) => row.grantable !== false && !mine.has(row.key)).sort((a, b) => a.label.localeCompare(b.label));
}

/** Scope choices for a permission: org-wide keys only take the org; team and project keys may be narrowed. */
export function scopesFor(row: CatalogRow | undefined): ("org" | "team" | "project")[] {
  if (!row) return ["org"];
  if (row.matrix === "team") return ["org", "team"];
  if (row.matrix === "project") return ["org", "project"];
  return ["org"];
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TRACKED = new Set([
  "",
  "/tasks",
  "/time",
  "/calendar",
  "/rooms",
  "/rooms/:id",
  "/rooms/:id/ai",
  "/rooms/:id/docs",
  "/rooms/:id/meetings",
  "/notifications",
  "/search",
  "/directory",
  "/members/:id",
  "/mission-control",
  "/ask",
  "/buddies",
  "/approvals",
  "/studio",
  "/learning",
  "/settings/access",
  "/settings/profile",
  "/settings/teams",
]);

/**
 * The screen a workspace path belongs to, with ids replaced (``/rooms/:id``), or null for screens
 * that are not counted. Never contains the org slug, ids or query strings.
 */
export function screenFor(pathname: string, slug: string): string | null {
  const prefix = `/w/${slug}`;
  if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) return null;
  const rest = pathname.slice(prefix.length).split(/[?#]/)[0].replace(/\/+$/, "");
  const shape = rest
    .split("/")
    .map((part) => (UUID.test(part) ? ":id" : part))
    .join("/");
  if (!TRACKED.has(shape)) return null;
  return shape || "/home";
}

/** Audit filters to query parameters. Dates are whole days (YYYY-MM-DD). */
export function auditQuery(f: { actor: string; action: string; since: string; until: string; page: number }): Record<string, string> {
  const out: Record<string, string> = { page: String(Math.max(1, f.page)) };
  if (f.actor) out.actor = f.actor;
  if (f.action.trim()) out.action = f.action.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.since)) out.since = f.since;
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.until)) out.until = f.until;
  return out;
}

/** A short browser label for feedback reports (no full user agent string). */
export function browserLabel(ua: string): string {
  const pick = (re: RegExp, name: string) => {
    const m = ua.match(re);
    return m ? `${name} ${m[1]}` : null;
  };
  return (
    pick(/Edg\/(\d+)/, "Edge") ||
    pick(/Firefox\/(\d+)/, "Firefox") ||
    pick(/Chrome\/(\d+)/, "Chrome") ||
    pick(/Version\/(\d+).*Safari/, "Safari") ||
    "Other browser"
  );
}
