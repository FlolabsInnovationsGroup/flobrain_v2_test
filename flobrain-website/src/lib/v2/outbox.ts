/**
 * Offline outbox for room messages (Phase 10 low-bandwidth mode).
 * Messages written while offline are kept in this browser and sent, in order,
 * when the connection returns. Nothing is kept after it is sent.
 * Each row belongs to the person who wrote it: another account signed in on the
 * same browser never sends it (review 10-13), and signing out clears the queue.
 */

const KEY = "flobrain_outbox_v1";

export type Queued = { id: string; userId: string; orgId: string; roomId: string; body: string; queuedAt: number };

/** The signed-in user's id from the access token (no verification needed: it only scopes local rows). */
export function currentUserId(): string {
  try {
    const token = window.localStorage.getItem("flobrain_access_token") || "";
    const part = token.split(".")[1] || "";
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.sub === "string" ? json.sub : "";
  } catch {
    return "";
  }
}

export function clear() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* blocked storage: nothing was kept */
  }
}

function read(): Queued[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const rows = raw ? (JSON.parse(raw) as Queued[]) : [];
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function write(rows: Queued[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rows.slice(-200)));
  } catch {
    /* storage full or blocked: the message stays in the composer instead */
  }
}

export function queue(orgId: string, roomId: string, body: string, userId = currentUserId()): Queued {
  const row = { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, userId, orgId, roomId, body, queuedAt: Date.now() };
  write([...read(), row]);
  return row;
}

export function pending(roomId?: string, userId = currentUserId()): Queued[] {
  return read().filter((row) => row.userId === userId && (!roomId || row.roomId === roomId));
}

/** Send queued messages in order; stop at the first network failure so order is kept. */
export async function flush(
  send: (row: Queued) => Promise<unknown>,
  isNetworkError: (err: unknown) => boolean,
  userId = currentUserId(),
): Promise<number> {
  let sent = 0;
  if (!userId) return 0;
  for (const row of read().filter((r) => r.userId === userId)) {
    try {
      await send(row);
      write(read().filter((r) => r.id !== row.id));
      sent += 1;
    } catch (err) {
      if (isNetworkError(err)) break;
      write(read().filter((r) => r.id !== row.id)); // refused by the server (for example no access): drop it
    }
  }
  return sent;
}
