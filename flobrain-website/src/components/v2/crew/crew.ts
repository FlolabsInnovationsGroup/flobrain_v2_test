/** Pure helpers for Flo, buddy feedback and the buddy quality page (growth round W5). */

export type Rating = "up" | "down";

/** "Not helpful" reasons. Codes match the backend (BuddyFeedback.REASONS). */
export const REASONS = [
  ["wrong", "Wrong answer"],
  ["incomplete", "Missing something"],
  ["off_topic", "Off topic"],
  ["no_sources", "No sources"],
  ["too_long", "Too long"],
  ["unsafe", "Unsafe or private"],
  ["other", "Other"],
] as const;

export type ReasonCode = (typeof REASONS)[number][0];

export function reasonLabel(code: string): string {
  return REASONS.find(([key]) => key === code)?.[1] ?? code;
}

/** Clicking the rating you already gave clears it (null); any other click sets it. */
export function nextRating(current: Rating | null, clicked: Rating): Rating | null {
  return current === clicked ? null : clicked;
}

/** The POST body for one rating. A reason or note only travels with "down". */
export function feedbackBody(messageId: number, rating: Rating, reason?: string, note?: string, buddy?: string) {
  const body: Record<string, unknown> = { message: messageId, rating };
  if (rating === "down" && reason) body.reason = reason;
  const trimmed = (note ?? "").trim().slice(0, 300);
  if (rating === "down" && trimmed) body.note = trimmed;
  if (buddy) body.buddy = buddy;
  return body;
}

export type QualityRow = {
  id: string;
  slug: string;
  name: string;
  icon: string;
  builtin: boolean;
  answers: number;
  ratings: number;
  helpful: number;
  not_helpful: number;
  helpful_rate: number | null;
  approvals: { proposed: number; approved: number; rejected: number; waiting: number };
  median_latency_ms: number | null;
  measured: number;
  with_sources_rate: number | null;
  tokens: number;
  cost: string;
  unpriced_calls: number;
  routed: number;
  routing_share: number | null;
  top_reasons: { reason: string; count: number }[];
};

export type QualityStats = {
  days: number;
  since: string;
  buddies: QualityRow[];
  totals: { answers: number; ratings: number; helpful_rate: number | null; proposed: number; approved: number; rejected: number };
  reasons: { reason: string; count: number }[];
  routing: { decisions: number; by_method: Record<string, number> };
  trend: { day: string; answers: number; helpful: number; not_helpful: number }[];
};

/** 0.8666 → "87%"; null → "–" (no data, not zero). */
export function percent(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "–" : `${Math.round(rate * 100)}%`;
}

/** 1534 → "1.5 s"; 840 → "840 ms". */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** 1_500_000 → "1.5M"; 12_400 → "12.4k". */
export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** "2.0000" → "$2.00"; tiny non-zero amounts keep a cent of precision. */
export function money(amount: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value) || value === 0) return "$0";
  return value < 0.01 ? "<$0.01" : `$${value.toFixed(2)}`;
}

/** "2026-10-21" → "Oct 21" in the viewer's locale. */
export function shortDay(day: string, locale?: string): string {
  const date = new Date(`${day}T00:00:00`);
  return Number.isNaN(date.getTime()) ? day : date.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** Rows with any activity first; buddies nobody used stay at the end so the table is not padded with zeros. */
export function activeFirst(rows: QualityRow[]): QualityRow[] {
  const busy = (r: QualityRow) => r.answers + r.ratings + r.approvals.proposed + r.routed;
  return [...rows].sort((a, b) => Number(busy(b) > 0) - Number(busy(a) > 0));
}
