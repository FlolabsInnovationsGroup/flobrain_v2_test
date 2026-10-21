export const MAX_TEXT = 300;

export const CATEGORIES = ["preference", "work_context", "project", "people", "other"] as const;
export type Category = (typeof CATEGORIES)[number];

export type MemoryItem = {
  id: string;
  scope: "person" | "team";
  text: string;
  category: Category;
  source: "buddy" | "chat" | "manual";
  confirmed: boolean;
  pinned: boolean;
  status: "active" | "pending";
  buddy: { id: string; name: string } | null;
  team: { id: string; name: string } | null;
  created_at: string;
  updated_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
};

export type Rules = {
  enabled: boolean;
  ask_before_saving: boolean;
  retention_days: number | null;
  blocked_categories: Category[];
  team_memory: boolean;
  updated_at?: string | null;
  totals?: { personal: number; team: number };
};

export type Summary = {
  rules: Rules;
  me: { paused: boolean };
  counts: { active: number; pending: number };
  categories: Category[];
  never_stored: string[];
  limits: { text: number; personal: number };
  can_manage: boolean;
  teams: { id: string; name: string }[];
};

export type TeamRow = { id: string; name: string; memories: number; members: number };

type Tr = (text: string, vars?: Record<string, string | number>) => string;

export function categoryLabel(tr: Tr, category: string): string {
  switch (category) {
    case "preference":
      return tr("Preference");
    case "work_context":
      return tr("Work context");
    case "project":
      return tr("Project");
    case "people":
      return tr("People you work with");
    default:
      return tr("Other");
  }
}

export function neverLabel(tr: Tr, key: string): string {
  const labels: Record<string, string> = {
    health: tr("Health"),
    religion: tr("Religion and beliefs"),
    politics: tr("Politics"),
    sexual_orientation: tr("Sexual orientation and relationships"),
    finances: tr("Money and salary"),
    government_id: tr("ID numbers"),
    card_number: tr("Card and bank details"),
    home_address: tr("Home address"),
    children: tr("Children's details"),
    credentials: tr("Passwords and keys"),
    special_category: tr("Ethnicity and criminal records"),
  };
  return labels[key] ?? key;
}

export function sourceLabel(tr: Tr, item: Pick<MemoryItem, "source" | "buddy" | "confirmed">): string {
  if (item.source === "manual") return tr("You added this");
  if (item.source === "chat") return tr("You asked a buddy to remember this");
  const who = item.buddy?.name ?? tr("A buddy");
  return item.confirmed ? tr("{name} suggested it, you said yes", { name: who }) : tr("{name} saved it from a chat", { name: who });
}

/** Search (every word, any order, ignoring case) and category filter, pinned first then newest. */
export function filterItems(items: MemoryItem[], query: string, category: Category | ""): MemoryItem[] {
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return items
    .filter((item) => !category || item.category === category)
    .filter((item) => {
      const text = item.text.toLocaleLowerCase();
      return words.every((w) => text.includes(w));
    })
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.created_at.localeCompare(a.created_at));
}

/** A short reason the text can't be saved yet, or "" when it looks fine (the server checks again). */
export function textProblem(tr: Tr, text: string): string {
  const value = text.trim();
  if (!value) return tr("Write the fact to remember.");
  if (value.length > MAX_TEXT) return tr("Keep it under {n} characters.", { n: MAX_TEXT });
  return "";
}

/** Retention as plain words. */
export function retentionLabel(tr: Tr, days: number | null): string {
  if (!days) return tr("Kept until someone deletes it");
  if (days % 365 === 0) return tr("Deleted after {n} year(s)", { n: days / 365 });
  if (days % 30 === 0) return tr("Deleted after {n} month(s)", { n: days / 30 });
  return tr("Deleted after {n} day(s)", { n: days });
}

export function splitByStatus(items: MemoryItem[]): { active: MemoryItem[]; pending: MemoryItem[] } {
  return { active: items.filter((i) => i.status === "active"), pending: items.filter((i) => i.status === "pending") };
}
