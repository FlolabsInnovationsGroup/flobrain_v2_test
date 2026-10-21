import type { CallFilters, Policy } from "./types";

export const EMPTY_FILTERS: CallFilters = { direction: "", ok: "", tool: "", client: "", days: "30" };

/** Query parameters for the call log: only the filters that are set. */
export function callQuery(filters: CallFilters): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) if (value) out[key] = value;
  return out;
}

/** The redacted argument shape as one short line: "title: text (23 chars), api_key: [hidden]". */
export function argsLine(args: Record<string, unknown>): string {
  const parts = Object.entries(args ?? {}).map(([key, value]) => {
    if (value && typeof value === "object") return `${key}: {${argsLine(value as Record<string, unknown>)}}`;
    return `${key}: ${String(value)}`;
  });
  return parts.join(", ");
}

export function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

/** "2026-12-31" from an ISO date-time, in local time, for <input type="date">. */
export function toDateInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The end of that local day as ISO, or null for "no end date". */
export function fromDateInput(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59).toISOString();
}

export type Draft = { rules: Record<string, "allow" | "deny">; readOnly: boolean; endDate: string; buddies: string[] };

export function draftFrom(policy: Policy): Draft {
  const rules: Record<string, "allow" | "deny"> = {};
  for (const tool of policy.tools) rules[tool.name] = policy.tool_rules[tool.name] ?? "allow";
  return { rules, readOnly: policy.read_only, endDate: toDateInput(policy.expires_at), buddies: [...policy.buddy_ids] };
}

/** The PUT body for a server's policy. */
export function policyBody(draft: Draft) {
  return { tool_rules: draft.rules, read_only: draft.readOnly, expires_at: fromDateInput(draft.endDate), buddy_ids: draft.buddies };
}

/** Whether a tool would be usable under the draft (same order as the server's check). */
export function toolUsable(draft: Draft, tool: { name: string; read_only: boolean }, expired: boolean): boolean {
  if (expired) return false;
  if (draft.rules[tool.name] === "deny") return false;
  return !(draft.readOnly && !tool.read_only);
}

export function isPast(dateInput: string, now = new Date()): boolean {
  const iso = fromDateInput(dateInput);
  return iso !== null && new Date(iso).getTime() <= now.getTime();
}

export function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}
