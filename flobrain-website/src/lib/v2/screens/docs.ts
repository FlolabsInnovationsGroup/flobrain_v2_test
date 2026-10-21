export type DocRow = { id: string; title: string; content_text: string; version: number };

export function docsEmpty(rows: DocRow[]): boolean {
  return rows.length === 0;
}

export function isVersionConflict(current: number, incoming: number): boolean {
  return current !== incoming;
}

export function nextDraft(doc: DocRow, content: string): { version: number; content_text: string } {
  return { version: doc.version, content_text: content };
}
