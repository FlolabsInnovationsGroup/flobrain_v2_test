export type ToolRow = { id: string; name: string; url: string };

export function toolsEmpty(rows: ToolRow[]): boolean {
  return rows.length === 0;
}

export function isValidToolUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

export function canCreateTool(name: string, url: string): boolean {
  return name.trim().length > 0 && isValidToolUrl(url);
}
