type Tr = (text: string, vars?: Record<string, string | number>) => string;

/** Decision 13 timestamps, in the reader's language: just now, X min ago, X hours ago, then the date. */
export function roomTime(iso: string | null | undefined, tr: Tr, now = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Math.max(0, now - then);
  if (diff < 60_000) return tr("just now");
  if (diff < 60 * 60_000) return tr("{n} min ago", { n: Math.floor(diff / 60_000) });
  if (diff < 24 * 60 * 60_000) return tr("{n} hours ago", { n: Math.floor(diff / 3_600_000) });
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

/** Split a message into plain text and @mentions so mentions can be highlighted (no HTML is rendered). */
export function mentionParts(body: string): { text: string; mention: boolean }[] {
  const parts: { text: string; mention: boolean }[] = [];
  const re = /(^|[^\w@])(@[\p{L}\p{N}_]+(?: [\p{Lu}][\p{L}\p{N}_]*)?)/gu;
  let last = 0;
  for (const m of body.matchAll(re)) {
    const start = (m.index ?? 0) + m[1].length;
    if (start > last) parts.push({ text: body.slice(last, start), mention: false });
    parts.push({ text: m[2], mention: true });
    last = start + m[2].length;
  }
  if (last < body.length) parts.push({ text: body.slice(last), mention: false });
  return parts;
}

/** The reader's translation target: the interface language. */
export function translateTarget(locale: string): string {
  return locale.split("-")[0] || "en";
}

export type RoomInfo = { id: string; name: string; kind: string; unread?: number; other_name?: string; other_user?: string };

export function roomTitle(room: Pick<RoomInfo, "name" | "kind" | "other_name">): string {
  return room.kind === "direct" && room.other_name ? room.other_name : room.name;
}
