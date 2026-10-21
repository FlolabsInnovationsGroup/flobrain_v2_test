export type ChatMessage = {
  id: string;
  body: string;
  translation?: string;
  translated?: boolean;
  created_at: string;
  author?: string | null;
};

export const ROOM_POLL_MS = 5000;

export function mergeMessages(existing: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const map = new Map<string, ChatMessage>();
  for (const row of [...existing, ...incoming]) map.set(row.id, row);
  return [...map.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function displayBody(message: ChatMessage, translate: boolean): string {
  if (translate && message.translation) return message.translation;
  return message.body;
}

export function canSendMessage(body: string): boolean {
  return body.trim().length > 0;
}

export function formatRoomTimestamp(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Math.max(0, now - then);
  if (diff < 60_000) return "just now";
  if (diff < 60 * 60_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 24 * 60 * 60_000) return `${Math.floor(diff / 3_600_000)} hours ago`;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function shouldPoll(open: boolean, hidden: boolean): boolean {
  return open && !hidden;
}

export function nextCursorFromUrl(next: string | null | undefined): string | null {
  if (!next) return null;
  try {
    const url = new URL(next, "http://local.invalid");
    return url.searchParams.get("cursor");
  } catch {
    return null;
  }
}

export async function loadCursorPages<T extends ChatMessage>(
  fetchPage: (cursor?: string) => Promise<{ results?: T[]; next?: string | null }>,
  maxPages = 5,
): Promise<T[]> {
  let rows: T[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < maxPages; i += 1) {
    const page = await fetchPage(cursor);
    rows = mergeMessages(rows, page.results ?? []) as T[];
    const next = nextCursorFromUrl(page.next);
    if (!next) break;
    cursor = next;
  }
  return rows;
}
