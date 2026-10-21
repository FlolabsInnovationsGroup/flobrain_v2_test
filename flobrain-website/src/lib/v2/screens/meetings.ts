export type MeetingRow = { id: string; title: string; join_url?: string };
export type RecordingRow = { id: string; play_url: string; recorded_at: string; meeting: string };

export function sortRecordings(rows: RecordingRow[], newestFirst: boolean): RecordingRow[] {
  return [...rows].sort((a, b) =>
    newestFirst ? b.recorded_at.localeCompare(a.recorded_at) : a.recorded_at.localeCompare(b.recorded_at),
  );
}

export function meetingsEmpty(meetings: MeetingRow[], recordings: RecordingRow[]): boolean {
  return meetings.length === 0 && recordings.length === 0;
}

export function needsConfirm(confirm: boolean): boolean {
  return !confirm;
}

export function canShowJoinUrl(joinUrl?: string | null): boolean {
  if (!joinUrl) return false;
  const value = joinUrl.toLowerCase();
  return !value.includes("meet.local") && (value.startsWith("https://") || value.startsWith("http://"));
}
