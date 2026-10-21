export type MeetingRow = {
  id: string;
  title: string;
  join_url?: string;
  started_at?: string | null;
  ended_at?: string | null;
  call_available?: boolean;
  recording?: boolean;
  has_summary?: boolean;
  can_manage?: boolean;
};
export type RecordingRow = {
  id: string;
  play_url: string;
  recorded_at: string;
  meeting: string;
  source?: "upload" | "livekit" | "bot";
  duration_seconds?: number | null;
  transcript_status?: "none" | "queued" | "running" | "done" | "failed";
  transcript_error?: string;
  speaker?: string;
};

/** "1:05:09" or "4:07" for a recording length. */
export function duration(seconds?: number | null): string {
  if (!seconds || seconds < 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

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
