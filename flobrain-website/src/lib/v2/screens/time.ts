export const CATEGORIES = [
  { id: "projects", label: "Projects" },
  { id: "onboarding", label: "Onboarding" },
  { id: "masterclass", label: "Masterclass" },
] as const;

export function categoryLabel(id: string | undefined): string {
  return CATEGORIES.find((c) => c.id === id)?.label ?? "Projects";
}

export type TimeEntryRow = {
  id: string;
  user?: string;
  user_name?: string;
  description: string;
  description_hidden?: boolean;
  started_at: string;
  ended_at: string | null;
  seconds: number;
  category: string;
  source?: string;
  task: string | null;
  task_title?: string;
  project: string | null;
  project_name?: string;
  room: string | null;
  room_name?: string;
  tags?: string[];
  approval_status: "draft" | "submitted" | "approved" | "rejected";
  approval_note?: string;
  can_edit?: boolean;
};

/** Seconds as h:mm (``0:05``, ``12:30``). Negative values keep their sign. */
export function formatDuration(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const total = Math.floor(Math.abs(seconds) / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${sign}${h}:${String(m).padStart(2, "0")}`;
}

/** Seconds as HH:MM:SS for the live timer. */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

/** The Monday (YYYY-MM-DD, local time) of the week that contains ``day``. */
export function mondayOf(day: Date): string {
  const d = new Date(day.getFullYear(), day.getMonth(), day.getDate());
  const offset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - offset);
  return ymd(d);
}

export function ymd(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function shiftWeek(monday: string, weeks: number): string {
  const d = new Date(+monday.slice(0, 4), +monday.slice(5, 7) - 1, +monday.slice(8, 10));
  d.setDate(d.getDate() + weeks * 7);
  return ymd(d);
}

export function weekEnd(monday: string): string {
  const d = new Date(+monday.slice(0, 4), +monday.slice(5, 7) - 1, +monday.slice(8, 10));
  d.setDate(d.getDate() + 6);
  return ymd(d);
}

/** ``<input type="datetime-local">`` value for an ISO time, in local time. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Back to an ISO string with the browser's offset, or "" when empty or invalid. */
export function fromLocalInput(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}

/** Client-side checks before a manual entry is sent (the server checks again). */
export function manualEntryProblem(start: string, end: string, now = new Date()): string | null {
  if (!start || !end) return "Add a start and an end.";
  const a = new Date(start).getTime();
  const b = new Date(end).getTime();
  if (Number.isNaN(a) || Number.isNaN(b)) return "Add a start and an end.";
  if (b <= a) return "The end must be after the start.";
  if (b > now.getTime() + 5 * 60 * 1000) return "You can't log time in the future.";
  if (b - a > 24 * 3600 * 1000) return "One entry can be at most 24 hours.";
  return null;
}

export function approvalTone(status: string): "neutral" | "waiting" | "good" | "bad" {
  if (status === "approved") return "good";
  if (status === "submitted") return "waiting";
  if (status === "rejected") return "bad";
  return "neutral";
}

export function approvalLabel(status: string): string {
  if (status === "submitted") return "Waiting for approval";
  if (status === "approved") return "Approved";
  if (status === "rejected") return "Sent back";
  return "Not submitted";
}

/** Share of ``total`` for a bar width (0..100). */
export function share(seconds: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((seconds / total) * 100)));
}
