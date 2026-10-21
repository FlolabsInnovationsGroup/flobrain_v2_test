/** Website chat (public page) helpers: API base, parent origin, token storage. */

export type PublicMessage = { id: string; role: "customer" | "buddy" | "staff" | "system"; text: string; created_at: string; citations: { n: number; title: string }[] };
export type PublicConfig = { name: string; greeting: string; embed_allowed: boolean; demo: boolean };

export function apiBase(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  return (url ? url.replace(/\/$/, "") : "http://127.0.0.1:8000") + "/api/v2/public/chat";
}

/** The page that embeds this chat, as the browser reports it (not what the URL claims), or "". */
export function parentOrigin(win: Pick<Window, "self" | "top" | "location" | "document"> & { location: Location & { ancestorOrigins?: DOMStringList } }, claimed = ""): string {
  let framed = false;
  try {
    framed = win.self !== win.top;
  } catch {
    framed = true;
  }
  if (!framed) return "";
  const ancestors = win.location.ancestorOrigins;
  if (ancestors && ancestors.length > 0) return ancestors[0];
  try {
    if (win.document.referrer) return new URL(win.document.referrer).origin;
  } catch {
    // fall through to what the embed script said
  }
  return claimed;
}

const KEY = (site: string) => `flobrain_chat_${site}`;

export function loadToken(site: string): string {
  try {
    return window.sessionStorage.getItem(KEY(site)) ?? "";
  } catch {
    return "";
  }
}

export function saveToken(site: string, token: string) {
  try {
    window.sessionStorage.setItem(KEY(site), token);
  } catch {
    // storage blocked: the chat still works for this page view
  }
}

/** Merge new messages into the list by id, oldest first. */
export function mergeMessages(current: PublicMessage[], incoming: PublicMessage[]): PublicMessage[] {
  const byId = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
}
