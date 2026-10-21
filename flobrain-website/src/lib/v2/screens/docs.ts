export type Person = { id: string; name: string } | null;

export type DocRow = {
  id: string;
  title: string;
  content_text: string;
  version: number;
  room?: string;
  created_by?: Person;
  updated_by?: Person;
  created_at?: string;
  updated_at?: string | null;
  can_delete?: boolean;
};

export type Revision = {
  version: number;
  created_by: Person;
  created_at: string;
  chars: number;
  current: boolean;
};

export type Attachment = {
  id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  download_url: string | null;
  created_by: Person;
  created_at: string;
};

export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict" | "readonly";

export function docsEmpty(rows: DocRow[]): boolean {
  return rows.length === 0;
}

export function isVersionConflict(current: number, incoming: number): boolean {
  return current !== incoming;
}

export function nextDraft(doc: DocRow, content: string): { version: number; content_text: string } {
  return { version: doc.version, content_text: content };
}

/** What an autosave sends: the version it started from, the text, and the title when it is not blank. */
export function savePayload(
  base: DocRow,
  title: string,
  text: string
): { version: number; content_text: string; title?: string } {
  const clean = title.trim();
  return clean && clean !== base.title
    ? { version: base.version, content_text: text, title: clean }
    : { version: base.version, content_text: text };
}

export function isDirty(base: DocRow, title: string, text: string): boolean {
  const clean = title.trim();
  return text !== base.content_text || (clean !== "" && clean !== base.title);
}

/** The draft kept in this browser until the server has it, so a failed save or a reload never loses it. */
export type DraftBackup = { version: number; title: string; text: string; at: string };

export const draftKey = (docId: string) => `fb-v2-doc-draft:${docId}`;

export function readBackup(docId: string): DraftBackup | null {
  try {
    const raw = window.localStorage.getItem(draftKey(docId));
    if (!raw) return null;
    const value = JSON.parse(raw) as DraftBackup;
    return typeof value?.text === "string" && typeof value?.version === "number" ? value : null;
  } catch {
    return null;
  }
}

export function writeBackup(docId: string, backup: DraftBackup | null): void {
  try {
    if (backup) window.localStorage.setItem(draftKey(docId), JSON.stringify(backup));
    else window.localStorage.removeItem(draftKey(docId));
  } catch {
    // Private mode or storage full: the in-memory draft still stays on screen.
  }
}

/**
 * How a draft found in this browser relates to the server copy:
 * "none" (nothing to restore), "restore" (same base version, just unsaved) or "conflict" (someone saved since).
 */
export function backupState(
  server: DocRow,
  backup: DraftBackup | null
): "none" | "restore" | "conflict" {
  if (!backup || !isDirty(server, backup.title, backup.text)) return "none";
  return backup.version === server.version ? "restore" : "conflict";
}

export type Markup = "bold" | "italic" | "heading" | "list" | "check" | "link" | "code";

/** Toolbar edits on a Markdown textarea: wrap the selection, or prefix the selected lines. */
export function applyMarkup(
  text: string,
  start: number,
  end: number,
  kind: Markup
): { text: string; start: number; end: number } {
  const selected = text.slice(start, end);
  const wrap = (left: string, right: string, placeholder: string) => {
    const inner = selected || placeholder;
    const next = text.slice(0, start) + left + inner + right + text.slice(end);
    return { text: next, start: start + left.length, end: start + left.length + inner.length };
  };
  if (kind === "bold") return wrap("**", "**", "bold text");
  if (kind === "italic") return wrap("_", "_", "italic text");
  if (kind === "code") return wrap("`", "`", "code");
  if (kind === "link") {
    const inner = selected || "link text";
    const next = `${text.slice(0, start)}[${inner}](https://)${text.slice(end)}`;
    const urlAt = start + inner.length + 3;
    return { text: next, start: urlAt, end: urlAt + "https://".length };
  }
  const prefix = kind === "heading" ? "## " : kind === "list" ? "- " : "- [ ] ";
  const lineStart = text.lastIndexOf("\n", start - 1) + 1;
  const block = text.slice(lineStart, end);
  const lines = block
    .split("\n")
    .map((line) => (line.startsWith(prefix) ? line.slice(prefix.length) : prefix + line));
  const replaced = lines.join("\n");
  return {
    text: text.slice(0, lineStart) + replaced + text.slice(end),
    start: lineStart,
    end: lineStart + replaced.length,
  };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Strip the API base so the path fits ``api``/``apiClientUpload`` helpers, which add it back. */
export function apiPath(url: string): string {
  return url.startsWith("/api/v2") ? url.slice("/api/v2".length) : url;
}
