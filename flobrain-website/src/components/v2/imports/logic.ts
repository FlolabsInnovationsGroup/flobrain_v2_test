import type { ChannelChoice, Place, Preview, Run, SlackChannel, SlackMapping, Source, Status } from "./types";

export const ACTIVE: Status[] = ["analyzing", "queued", "running", "undoing"];

export function isActive(run: Pick<Run, "status"> | null | undefined): boolean {
  return !!run && ACTIVE.includes(run.status);
}

/** The files each upload source accepts; the server checks again. */
export function acceptedFile(source: Source, name: string): boolean {
  const lower = name.toLowerCase();
  if (source === "files") return /\.(zip|docx|pdf|txt|md|markdown|csv|html?)$/.test(lower);
  return lower.endsWith(".zip");
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 KB";
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** 0..100, or null when the total is not known yet. */
export function percent(run: Pick<Run, "progress" | "status">): number | null {
  if (run.status === "done" || run.status === "undone") return 100;
  const total = run.progress?.total ?? 0;
  if (!total) return null;
  return Math.max(0, Math.min(100, Math.round(((run.progress?.done ?? 0) / total) * 100)));
}

export type Tone = "neutral" | "good" | "bad" | "accent";

/** Green for done, rose for failed, violet while working. Amber is for approvals only. */
export function statusTone(status: Status): Tone {
  if (status === "done") return "good";
  if (status === "failed") return "bad";
  if (ACTIVE.includes(status) || status === "ready") return "accent";
  return "neutral";
}

export const STATUS_LABEL: Record<Status, string> = {
  analyzing: "Reading the file",
  ready: "Waiting for your choices",
  queued: "Starting",
  running: "Importing",
  done: "Done",
  failed: "Failed",
  cancelled: "Stopped",
  undoing: "Undoing",
  undone: "Undone",
};

export const SOURCE_LABEL: Record<Source, string> = {
  slack: "Slack export",
  notion_zip: "Notion export",
  notion_api: "Notion",
  drive_api: "Google Drive",
  files: "Files",
};

/** Count keys the history shows, in order, with their English label. */
const COUNT_LABELS: [string, string][] = [
  ["messages", "{n} messages"],
  ["documents", "{n} documents"],
  ["rooms_created", "{n} new rooms"],
  ["teams_created", "{n} new teams"],
  ["messages_existing", "{n} already imported"],
  ["documents_existing", "{n} already imported"],
  ["files_too_big", "{n} too big"],
  ["files_pdf_unavailable", "{n} PDFs skipped"],
  ["files_unreadable", "{n} unreadable"],
  ["channels_without_people", "{n} channels without matched people"],
];

export function countLines(counts: Record<string, number> | undefined): { template: string; n: number }[] {
  if (!counts) return [];
  return COUNT_LABELS.filter(([key]) => (counts[key] ?? 0) > 0).map(([key, template]) => ({ template, n: counts[key] }));
}

/** The error code before the colon, and the readable part after it. */
export function errorParts(error: string): { code: string; text: string } {
  const at = error.indexOf(":");
  if (at < 0) return { code: error, text: error };
  return { code: error.slice(0, at).trim(), text: error.slice(at + 1).trim() };
}

function normal(name: string): string {
  return name.trim().toLowerCase().replace(/^#/, "");
}

/** First guess for each channel: a team with the same name, otherwise a new team; private channels and DMs become private rooms. */
export function defaultChoice(channel: SlackChannel, teams: Place[]): ChannelChoice {
  if (channel.kind !== "public") return { target: channel.matched > 0 ? "private" : "skip" };
  const team = teams.find((t) => t.id === channel.suggested_team) ?? teams.find((t) => normal(t.name) === normal(channel.name));
  if (team) return { target: "team", team_id: team.id };
  if (channel.archived || channel.messages === 0) return { target: "skip" };
  return { target: "new_team" };
}

export function defaultMapping(preview: Preview | undefined, teams: Place[]): SlackMapping {
  const channels: Record<string, ChannelChoice> = {};
  for (const c of preview?.channels ?? []) channels[c.id] = defaultChoice(c, teams);
  return { channels, include_private: !!preview?.has_private, include_dms: false, include_bots: false };
}

/** What will actually be sent: skipped channels and channels left out by the opt-ins are dropped. */
export function mappingToSend(mapping: SlackMapping, channels: SlackChannel[]): SlackMapping {
  const out: Record<string, ChannelChoice> = {};
  for (const c of channels) {
    const choice = mapping.channels[c.id];
    if (!choice || choice.target === "skip") continue;
    if (c.kind === "private" && !mapping.include_private) continue;
    if ((c.kind === "dm" || c.kind === "group_dm") && !mapping.include_dms) continue;
    if (choice.target === "team" && !choice.team_id) continue;
    out[c.id] = choice.target === "team" ? { target: "team", team_id: choice.team_id } : { target: choice.target };
  }
  return { ...mapping, channels: out };
}

export function selectedMessages(mapping: SlackMapping, channels: SlackChannel[]): number {
  const chosen = mappingToSend(mapping, channels).channels;
  return channels.filter((c) => chosen[c.id]).reduce((sum, c) => sum + c.messages, 0);
}

export function dateRange(first: string, last: string, locale?: string): string {
  if (!first) return "";
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(locale, { dateStyle: "medium" });
  return first.slice(0, 10) === last.slice(0, 10) || !last ? fmt(first) : `${fmt(first)} – ${fmt(last)}`;
}
