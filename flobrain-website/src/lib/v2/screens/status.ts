export type ScreenState = "loading" | "empty" | "ready" | "no-access" | "error" | "off";

export function screenStateFromHttp(status: number, isEmpty = false): ScreenState {
  if (status === 401 || status === 403 || status === 404) return "no-access";
  if (status === 501) return "off";
  if (status === 0 || status >= 500) return "error";
  if (status >= 400) return "error";
  if (isEmpty) return "empty";
  return "ready";
}

export function isEmptyList(value: unknown): boolean {
  if (Array.isArray(value)) return value.length === 0;
  if (value && typeof value === "object" && "results" in value) {
    const results = (value as { results?: unknown }).results;
    return Array.isArray(results) && results.length === 0;
  }
  return value == null;
}
