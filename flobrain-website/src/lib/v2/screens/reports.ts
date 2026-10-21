export type TimeEntryLike = { seconds: number };

export function sumEntrySeconds(entries: TimeEntryLike[]): number {
  return entries.reduce((total, entry) => total + entry.seconds, 0);
}

export function weeklyTotalMatchesEntries(
  report: { seconds: number },
  entries: TimeEntryLike[],
): boolean {
  return report.seconds === sumEntrySeconds(entries);
}
