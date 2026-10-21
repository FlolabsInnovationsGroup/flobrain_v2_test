/** Content Studio types and pure helpers (EDL editing, ranges, calendar). No React here. */

import { getApiBaseUrl } from "@/lib/axios";

export type Word = { w: string; start: number; end: number; speaker?: string };
export type Asset = {
  id: string;
  kind: "video" | "audio" | "image";
  name: string;
  content_type: string;
  size_bytes: number;
  status: "pending" | "ready";
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  has_transcript: boolean;
  transcript_status: "" | "running" | "done" | "failed";
  uploaded_by: string | null;
  created_at: string;
  url?: string;
  upload_url?: string;
};
export type Project = {
  id: string;
  title: string;
  owner: string;
  status: string;
  source_assets: string[];
  brand_kit: string | null;
  template: string | null;
  target_platforms: string[];
  updated_at: string;
};
export type CutOp = { op: "cut"; asset: string; start: number; end: number; reason?: string; by?: "ai" | "user" };
export type KeepOp = { op: "keep"; asset: string; start: number; end: number };
export type Op =
  | CutOp
  | KeepOp
  | { op: "captions"; language: string; burn_in: boolean }
  | { op: "reframe"; aspect: Aspect; mode?: "auto" | "manual"; crop?: { x: number; y: number; w: number; h: number } }
  | { op: "overlay"; kind: "text" | "logo"; text: string; position: string; start: number; end: number }
  | { op: "intro" }
  | { op: "outro" }
  | { op: "music"; asset: string; volume: number };
export type Edl = { version: number; operations: Op[]; created_by_kind?: "user" | "ai"; note?: string; created_at?: string };
export type Clip = { id: string; asset: string; start: number; end: number; hook_text: string; score: number; reason: string; accepted: boolean };
export type Render = {
  id: string;
  project: string;
  project_title?: string;
  preset: Preset;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  edl_version: number | null;
  error: string;
  gpu_seconds: number;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  demo: boolean;
  output_url?: string;
  output?: { width: number; height: number; duration_seconds: number; codec: string };
};
export type PublishJob = {
  id: string;
  project: string;
  render: string;
  social_account: string;
  platform: string;
  title: string;
  description: string;
  hashtags: string[];
  scheduled_at: string | null;
  status: "awaiting_approval" | "approved" | "scheduled" | "publishing" | "published" | "failed" | "cancelled";
  hash: string;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  external_url: string | null;
  visibility: string | null;
  error: string;
};
export type Account = { id: string; platform: string; display_name: string; status: string; private_only: boolean; scopes: string[] };
export type PlatformInfo = {
  platform: string;
  label: string;
  configured: boolean;
  posts_private_until_audit: boolean;
  capabilities: { max_duration_seconds: number; aspect_ratios: string[]; caption_max: number };
};
export type Consent = {
  id: string;
  person_user: string | null;
  person_name: string;
  scope: "internal" | "public_social" | "marketing";
  media_asset: string | null;
  granted_at: string;
  revoked_at: string | null;
};
export type TaggedPerson = { id: string; user_id: string | null; name: string; email: string | null; consented: boolean };
export type People = { asset: string; people: number; tagged: TaggedPerson[]; face_count: number | null; can_remove: boolean };
export type ConsentProblem = { asset: string; asset_name: string; problem: "missing_consent" | "untagged_faces"; person?: string; person_name?: string; count?: number };
export type Kit = {
  id: string;
  name: string;
  colors: Record<string, string>;
  fonts: Record<string, string>;
  caption_style: Record<string, string>;
  watermark: Record<string, unknown>;
  intro_asset: string | null;
  outro_asset: string | null;
  logos: string[];
};
export type Template = {
  id: string;
  name: string;
  kind: string;
  builtin: boolean;
  spec: { duration_seconds?: number; resolution?: number[]; variables?: Record<string, { maxLength?: number; required?: boolean }> };
};
export type Member = { id: string; username: string };
export type PlatformCopy = Record<string, { title: string; description: string; hashtags: string[] }>;

export type Aspect = "9:16" | "1:1" | "16:9";
export type Preset = "9x16_1080" | "1x1_1080" | "16x9_1080" | "custom";
export const PRESET_FOR: Record<Aspect, Preset> = { "9:16": "9x16_1080", "1:1": "1x1_1080", "16:9": "16x9_1080" };
export const ASPECT_FOR: Record<string, Aspect> = { "9x16_1080": "9:16", "1x1_1080": "1:1", "16x9_1080": "16:9" };

/** Platforms the copy and target fields accept, with the aspect each one plays best. */
export const PLATFORMS = ["youtube", "linkedin", "tiktok", "instagram", "facebook", "x"] as const;
export const PLATFORM_LABEL: Record<string, string> = {
  youtube: "YouTube",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
  instagram: "Instagram",
  facebook: "Facebook",
  x: "X",
  sandbox: "Sandbox",
};
export const BEST_ASPECT: Record<string, Aspect[]> = {
  youtube: ["16:9", "9:16"],
  linkedin: ["1:1", "16:9", "9:16"],
  tiktok: ["9:16"],
  instagram: ["9:16", "1:1"],
  facebook: ["1:1", "16:9", "9:16"],
  x: ["16:9", "1:1"],
};

export const FILLERS = new Set(["um", "uh", "erm", "hmm", "like", "يعني", "اه", "آه", "ام", "اممم"]);

/** Presigned URLs from local storage are API-relative; S3 URLs are absolute. */
export function mediaUrl(url: string | undefined | null): string {
  if (!url) return "";
  if (/^https?:\/\//.test(url)) return url;
  return `${getApiBaseUrl()}${url.startsWith("/") ? "" : "/"}${url}`;
}

export function clock(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round((seconds ?? 0) * 10) / 10);
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}

export function bareWord(w: string): string {
  return w.replace(/[.,!?؟،]/g, "").toLowerCase();
}

export function cutsOf(ops: Op[], asset: string): CutOp[] {
  return ops.filter((o): o is CutOp => o.op === "cut" && o.asset === asset);
}

export function keepsOf(ops: Op[], asset?: string): KeepOp[] {
  return ops.filter((o): o is KeepOp => o.op === "keep" && (asset === undefined || o.asset === asset));
}

/** For each word: is it inside a cut? (a cut covers a word when it overlaps it) */
export function removedMask(words: Word[], ops: Op[], asset: string): boolean[] {
  const cuts = cutsOf(ops, asset);
  return words.map((w) => cuts.some((c) => c.start < w.end && c.end > w.start));
}

/** For each word: is it inside a kept segment? Without keeps, everything is kept. */
export function keptMask(words: Word[], ops: Op[], asset: string): boolean[] {
  const keeps = keepsOf(ops, asset);
  if (!keeps.length) return words.map(() => true);
  return words.map((w) => keeps.some((k) => k.start <= w.start && w.end <= k.end));
}

/** The source span of words i..j (inclusive), on word boundaries. */
export function spanOf(words: Word[], i: number, j: number): { start: number; end: number } {
  const [a, b] = i <= j ? [i, j] : [j, i];
  return { start: words[a].start, end: words[b].end };
}

function round(n: number) {
  return Math.round(n * 1000) / 1000;
}

/** Add a user cut over words i..j, merging with cuts it touches. */
export function addCut(ops: Op[], asset: string, words: Word[], i: number, j: number, reason = "user"): Op[] {
  const span = spanOf(words, i, j);
  let start = span.start;
  let end = span.end;
  const rest: Op[] = [];
  for (const op of ops) {
    if (op.op === "cut" && op.asset === asset && op.start <= end && op.end >= start) {
      start = Math.min(start, op.start);
      end = Math.max(end, op.end);
    } else {
      rest.push(op);
    }
  }
  return [...rest, { op: "cut", asset, start: round(start), end: round(end), reason, by: "user" }];
}

/** Remove every cut that overlaps words i..j (restores them). */
export function restoreRange(ops: Op[], asset: string, words: Word[], i: number, j: number): Op[] {
  const span = spanOf(words, i, j);
  return ops.filter((op) => !(op.op === "cut" && op.asset === asset && op.start < span.end && op.end > span.start));
}

/** User cuts for every filler word not already removed. */
export function removeFillers(ops: Op[], asset: string, words: Word[]): { ops: Op[]; count: number } {
  const removed = removedMask(words, ops, asset);
  let out = ops;
  let count = 0;
  words.forEach((w, i) => {
    if (!removed[i] && FILLERS.has(bareWord(w.w))) {
      out = [...out, { op: "cut", asset, start: w.start, end: w.end, reason: "filler", by: "user" }];
      count += 1;
    }
  });
  return { ops: out, count };
}

export function addKeep(ops: Op[], asset: string, words: Word[], i: number, j: number): Op[] {
  const span = spanOf(words, i, j);
  return [...ops, { op: "keep", asset, start: round(span.start), end: round(span.end) }];
}

/** Move the n-th keep segment up (-1) or down (+1) in playing order. Other operations keep their places. */
export function moveKeep(ops: Op[], n: number, delta: -1 | 1): Op[] {
  const positions = ops.map((o, i) => (o.op === "keep" ? i : -1)).filter((i) => i >= 0);
  const m = n + delta;
  if (n < 0 || m < 0 || n >= positions.length || m >= positions.length) return ops;
  const out = [...ops];
  [out[positions[n]], out[positions[m]]] = [out[positions[m]], out[positions[n]]];
  return out;
}

export function removeOp(ops: Op[], target: Op): Op[] {
  return ops.filter((o) => o !== target);
}

/** Replace the single op of a kind (captions, reframe, intro, outro) or remove it with null. */
export function setSingle(ops: Op[], kind: "captions" | "reframe" | "intro" | "outro", value: Op | null): Op[] {
  const rest = ops.filter((o) => o.op !== kind);
  return value ? [...rest, value] : rest;
}

export function findOp<K extends Op["op"]>(ops: Op[], kind: K): Extract<Op, { op: K }> | undefined {
  return ops.find((o) => o.op === kind) as Extract<Op, { op: K }> | undefined;
}

/** Seconds that survive the edit for one asset (keeps in order, minus cuts). */
export function keptSeconds(ops: Op[], asset: string, duration: number): number {
  const keeps = keepsOf(ops, asset);
  let ranges: [number, number][] = keeps.length ? keeps.map((k) => [k.start, k.end]) : [[0, duration]];
  for (const c of cutsOf(ops, asset).sort((a, b) => a.start - b.start)) {
    const next: [number, number][] = [];
    for (const [a, b] of ranges) {
      if (c.end <= a || c.start >= b) next.push([a, b]);
      else {
        if (c.start > a) next.push([a, c.start]);
        if (c.end < b) next.push([c.end, b]);
      }
    }
    ranges = next;
  }
  return ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
}

/** Index of the word playing at time t, or -1. */
export function wordAt(words: Word[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].end < t) lo = mid + 1;
    else if (words[mid].start > t) hi = mid - 1;
    else return mid;
  }
  return -1;
}

export function isActive(r: Render): boolean {
  return r.status === "queued" || r.status === "running";
}

/** Local date key (YYYY-MM-DD) for grouping calendar posts. */
export function dayKey(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => (n < 10 ? `0${n}` : String(n));
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The 6x7 grid of days shown for a month (weeks start on Monday). */
export function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - offset + i));
}

export function whenOf(job: PublishJob): string | null {
  return job.scheduled_at ?? (job.status === "published" ? job.approved_at : null);
}

/** "datetime-local" value → ISO with the browser's time zone, as the API requires. */
export function localToIso(value: string): string {
  return value ? new Date(value).toISOString() : "";
}

/** Split typed rows into template variables: one line per video, fields separated by "|". */
export function parseRows(text: string, fields: string[]): Record<string, string>[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = fields.length > 1 ? line.split("|").map((p) => p.trim()) : [line];
      return Object.fromEntries(fields.map((f, i) => [f, parts[i] ?? ""]).filter(([, v]) => v !== ""));
    });
}
