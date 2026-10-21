export type SearchHit = { type: string; id: string; title: string };

export const SEARCH_TYPES = ["rooms", "tasks", "docs", "meetings"] as const;

export function searchEmpty(query: string, results: SearchHit[]): boolean {
  return query.trim().length > 0 && results.length === 0;
}

export function filterHits(results: SearchHit[], type: string | "all"): SearchHit[] {
  if (type === "all") return results;
  return results.filter((row) => row.type === type);
}
