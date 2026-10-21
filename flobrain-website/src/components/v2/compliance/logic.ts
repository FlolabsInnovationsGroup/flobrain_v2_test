import type { CheckStatus, Control, Decision, ReviewItem, Subprocessor, TrustDocument } from "./types";

export type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";

/** Green for passing, rose for a gap, neutral for "needs a person" and "not applicable". Amber is never used here. */
export function statusTone(status: CheckStatus): Tone {
  if (status === "pass") return "good";
  if (status === "fail") return "bad";
  return "neutral";
}

export type ControlFilter = { framework: string; status: string; group: string; q: string };

export function filterControls(controls: Control[], f: ControlFilter): Control[] {
  const q = f.q.trim().toLowerCase();
  return controls.filter(
    (c) =>
      (!f.framework || c.framework === f.framework) &&
      (!f.status || c.status === f.status) &&
      (!f.group || c.group === f.group) &&
      (!q || c.id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || c.summary.toLowerCase().includes(q)),
  );
}

/** Groups for the filter, in catalog order, for one framework (or all). */
export function groupsOf(controls: Control[], framework: string): { key: string; name: string }[] {
  const seen = new Map<string, string>();
  for (const c of controls) if (!framework || c.framework === framework) if (!seen.has(c.group)) seen.set(c.group, c.group_name);
  return [...seen.entries()].map(([key, name]) => ({ key, name }));
}

export function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

export type KeyAction = { type: "move"; index: number } | { type: "decide"; decision: Exclude<Decision, "pending"> } | { type: "help" } | null;

/**
 * Review shortcuts: j or ↓ next, k or ↑ previous, 1 keep, 2 revoke, 3 change, ? help.
 * Ignored while typing in a field or with a modifier held.
 */
export function reviewKey(e: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; target?: unknown }, index: number, length: number): KeyAction {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  const tag = (e.target as { tagName?: string } | null)?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return null;
  if (!length) return null;
  switch (e.key) {
    case "j":
    case "ArrowDown":
      return { type: "move", index: Math.min(length - 1, index + 1) };
    case "k":
    case "ArrowUp":
      return { type: "move", index: Math.max(0, index - 1) };
    case "1":
      return { type: "decide", decision: "keep" };
    case "2":
      return { type: "decide", decision: "revoke" };
    case "3":
      return { type: "decide", decision: "change" };
    case "?":
      return { type: "help" };
    default:
      return null;
  }
}

/** The next item still waiting for a decision after ``from`` (wrapping), or ``from`` when none is left. */
export function nextPending(items: Pick<ReviewItem, "decision" | "can_decide">[], from: number): number {
  const n = items.length;
  for (let step = 1; step <= n; step++) {
    const i = (from + step) % n;
    if (items[i].decision === "pending" && items[i].can_decide) return i;
  }
  return from;
}

/** Only membership and grant items can be changed; the rest are kept or revoked. */
export function canChange(item: Pick<ReviewItem, "kind" | "details">): boolean {
  if (item.kind === "grant") return true;
  return item.kind === "membership" && item.details.org_role !== "owner";
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function shortHash(sha: string): string {
  return sha ? `${sha.slice(0, 12)}…` : "";
}

export function emptySubprocessor(): Subprocessor {
  return { name: "", purpose: "", location: "", website: "" };
}

export function emptyDocument(): TrustDocument {
  return { key: "", title: "", description: "" };
}

export function updateAt<T>(rows: T[], index: number, patch: Partial<T>): T[] {
  return rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

export function removeAt<T>(rows: T[], index: number): T[] {
  return rows.filter((_, i) => i !== index);
}

export function toggle<T>(list: T[], value: T, order: T[]): T[] {
  const set = new Set(list);
  if (set.has(value)) set.delete(value);
  else set.add(value);
  return order.filter((v) => set.has(v));
}

/** Websites must be https; anything else is dropped before saving (the server does the same). */
export function cleanSubprocessors(rows: Subprocessor[]): Subprocessor[] {
  return rows
    .map((r) => ({ ...r, name: r.name.trim(), website: r.website.trim().startsWith("https://") ? r.website.trim() : "" }))
    .filter((r) => r.name);
}

/** An ISO date (YYYY-MM-DD) ``days`` before ``from``. */
export function isoDaysAgo(days: number, from = new Date()): string {
  const d = new Date(from.getTime() - days * 86_400_000);
  return d.toISOString().slice(0, 10);
}
