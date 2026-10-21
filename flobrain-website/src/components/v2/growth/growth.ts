/** Shared types and pure helpers for the Academy, industry packs, ratings and the AI seat meter. */

export type LessonProgress = {
  read: boolean;
  tried: boolean;
  attempts: number;
  best_score: number;
  completed: boolean;
  completed_at: string | null;
};

export type LessonSummary = {
  key: string;
  title: string;
  summary: string;
  minutes: number;
  feature: string | null;
  try_it: { label: string; path: string };
  questions: number;
  progress: LessonProgress;
};

export type CheckQuestion = { question: string; question_ar: string; options: string[]; options_ar: string[] };

export type LessonDetail = LessonSummary & { body: string; body_ar: string; check: CheckQuestion[] };

export type Academy = { lessons: LessonSummary[]; done: number; total: number; badge: { awarded_at: string } | null };

export type CheckResult = {
  score: number;
  passed: boolean;
  correct: boolean[];
  answers: number[] | null;
  progress: LessonProgress;
  badge_awarded: boolean;
};

export type PackItem = {
  key: string;
  kind: "room" | "doc" | "buddy" | "automation" | "time_tag";
  label: string;
  detail: string;
  action: "create" | "skip" | "installed" | "removed";
  needs: string;
  from_template?: boolean;
};

export type PackSummary = {
  key: string;
  name: string;
  summary: string;
  audience: string;
  version: number;
  counts: Partial<Record<PackItem["kind"], number>>;
  installed: boolean;
  installed_at: string | null;
};

export type PackPreview = { pack: PackSummary; items: PackItem[]; counts: Record<PackItem["action"], number> };

export type Allowance = {
  sample: boolean;
  unit: string;
  plan: { code: string; name: string | null; subscribed: boolean };
  included_per_seat: number;
  seats: number;
  included_total: number;
  used: number;
  used_pct: number;
  projected: number;
  projected_pct: number;
  over_projected: boolean;
  period: { start: string; end: string; days_in_month: number; days_elapsed: number };
  mine: { used: number; included_per_seat: number; pct: number };
  people?: { user_id: string | null; name: string; used: number }[];
};

/** Arabic body when the interface is Arabic and the lesson has one; English otherwise. */
export function localized(locale: string, english: string, arabic?: string): string {
  return locale === "ar" && arabic ? arabic : english;
}

/** Whole percent, clamped to 0..100 for drawing bars (labels show the real number). */
export function barPercent(part: number, whole: number): number {
  if (!whole || whole <= 0 || !Number.isFinite(part)) return 0;
  return Math.max(0, Math.min(100, Math.round((100 * part) / whole)));
}

/** Meter state: "over" once use passes the allowance, "trending" when the projection does, else "ok". */
export function meterState(a: Pick<Allowance, "used" | "included_total" | "projected">): "ok" | "trending" | "over" {
  if (a.included_total > 0 && a.used > a.included_total) return "over";
  if (a.included_total > 0 && a.projected > a.included_total) return "trending";
  return "ok";
}

/** Stars as five booleans for drawing, rounded to whole stars. */
export function starFill(average: number | null | undefined): boolean[] {
  const filled = Math.round(average ?? 0);
  return [1, 2, 3, 4, 5].map((n) => n <= filled);
}

/** Items of a preview grouped for display: what will be created, what is skipped, what is already there. */
export function groupPreview(items: PackItem[]) {
  return {
    create: items.filter((i) => i.action === "create"),
    skip: items.filter((i) => i.action === "skip"),
    installed: items.filter((i) => i.action === "installed" || i.action === "removed"),
  };
}

/** Prefix an in-product path from a lesson's "try it" with the workspace. Only relative app paths are allowed. */
export function workspaceHref(orgSlug: string, path: string): string {
  const safe = /^\/(?!\/)[a-z0-9/_-]*$/i.test(path) ? path : "";
  return `/w/${orgSlug}${safe}`;
}

/** The lesson to open next: the first one not completed, or null when all are. */
export function firstOpen(lessons: LessonSummary[]): LessonSummary | null {
  return lessons.find((l) => !l.progress.completed) ?? null;
}
