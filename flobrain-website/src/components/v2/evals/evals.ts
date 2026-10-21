/** Types and pure helpers for buddy evals (market round M5). */

export type Language = "any" | "ar" | "en";

export type EvalCase = {
  id: string;
  set: string;
  position: number;
  name: string;
  input: string;
  context_doc_ids: string[];
  context_docs: { id: string; title: string }[];
  must_include: string[];
  must_not_include: string[];
  must_cite: boolean;
  expected_tool: string;
  forbidden_tools: string[];
  max_words: number | null;
  language: Language;
  rubric: string;
  updated_at?: string;
};

export type RunSummary = {
  id: string;
  set: string;
  buddy: string;
  status: "queued" | "running" | "done" | "stopped" | "error";
  passed: boolean | null;
  score: number | null;
  threshold: number;
  cases_total: number;
  cases_passed: number;
  version: string;
  fingerprint: string;
  tools: string[];
  model: string;
  judge_model: string;
  tokens: number;
  cost: string;
  duration_ms: number | null;
  triggered_by: "manual" | "schedule" | "gate";
  gate_context: string;
  error: string;
  by: { id: string; name: string } | null;
  created_at: string;
  finished_at: string | null;
};

export type CheckRow = { check: string; passed: boolean; expected: unknown; got: unknown; reason: string };
export type Judge = { valid: boolean; score?: number; reason?: string; error?: string };

export type CaseResult = {
  case: string;
  name: string;
  input: string;
  expect: Partial<Pick<EvalCase, "must_include" | "must_not_include" | "must_cite" | "expected_tool" | "forbidden_tools" | "max_words" | "language" | "rubric">>;
  answer: string;
  calls: { tool: string; args?: Record<string, unknown>; offered?: boolean; valid?: boolean; external?: boolean }[];
  checks: CheckRow[];
  judge: Judge | null;
  passed: boolean;
  score: number;
  error: string;
  sources: { id: string; title: string }[];
  missing_sources: number;
  hidden?: boolean;
  tokens: number;
  duration_ms: number;
};

export type RunDetail = RunSummary & {
  results: CaseResult[];
  previous: RunSummary | null;
  previous_results?: Record<string, { passed: boolean; score: number }>;
};

export type TrendPoint = { run: string; at: string; score: number; passed: boolean | null; version: string; triggered_by: RunSummary["triggered_by"] };

export type EvalSet = {
  id: string;
  buddy: { id: string; name: string; icon: string };
  name: string;
  description: string;
  threshold: number;
  max_drop: number;
  gate_marketplace: boolean;
  gate_saves: boolean;
  schedule: "off" | "daily" | "weekly";
  cases_count: number;
  latest_run: RunSummary | null;
  baseline: { run: string; score: number | null; version: string } | null;
  current_fingerprint: string;
  created_at: string;
  cases?: EvalCase[];
  trend?: TrendPoint[];
};

export type Overview = {
  buddies: { id: string; name: string; icon: string; builtin: boolean; sets: number; latest: { score: number; passed: boolean | null; at: string } | null }[];
  tools: { key: string; label: string }[];
  judge_models: string[];
};

export type GateSetRow = {
  set: string;
  name: string;
  run: string;
  reused: boolean;
  status: string;
  score: number | null;
  threshold: number;
  previous: number | null;
  max_drop: number;
  cases_passed: number;
  cases_total: number;
  failed_cases: string[];
  passed: boolean;
  reason: string;
};

export type GateResult = { allowed: boolean; outcome: "skipped" | "passed" | "blocked" | "overridden"; message: string; sets: GateSetRow[] };

export type GateEvent = {
  id: string;
  buddy: { id: string; name: string };
  context: "marketplace" | "save" | "check";
  outcome: "passed" | "blocked" | "overridden";
  details: GateSetRow[];
  override_reason: string;
  by: { id: string; name: string } | null;
  created_at: string;
};

export type Policy = { judge_model: string; max_run_tokens: number; max_run_cost: string | null; concurrency: number };

/** The editable form of a case: lists as one phrase per line, numbers as text. */
export type CaseDraft = {
  name: string;
  input: string;
  docs: { id: string; title: string }[];
  mustInclude: string;
  mustNotInclude: string;
  mustCite: boolean;
  expectedTool: string;
  forbiddenTools: string[];
  maxWords: string;
  language: Language;
  rubric: string;
};

export const EMPTY_DRAFT: CaseDraft = {
  name: "",
  input: "",
  docs: [],
  mustInclude: "",
  mustNotInclude: "",
  mustCite: false,
  expectedTool: "",
  forbiddenTools: [],
  maxWords: "",
  language: "any",
  rubric: "",
};

export function lines(text: string): string[] {
  return [...new Set(text.split("\n").map((l) => l.trim()).filter(Boolean))];
}

export function draftFrom(c: Partial<EvalCase>): CaseDraft {
  return {
    name: c.name ?? "",
    input: c.input ?? "",
    docs: c.context_docs ?? (c.context_doc_ids ?? []).map((id) => ({ id, title: "" })),
    mustInclude: (c.must_include ?? []).join("\n"),
    mustNotInclude: (c.must_not_include ?? []).join("\n"),
    mustCite: !!c.must_cite,
    expectedTool: c.expected_tool ?? "",
    forbiddenTools: c.forbidden_tools ?? [],
    maxWords: c.max_words ? String(c.max_words) : "",
    language: c.language ?? "any",
    rubric: c.rubric ?? "",
  };
}

/** What the API takes. Returns an error key instead when the draft can't be sent. */
export function draftPayload(d: CaseDraft): { ok: true; body: Record<string, unknown> } | { ok: false; error: "input" | "max_words" | "conflict" } {
  if (!d.input.trim()) return { ok: false, error: "input" };
  let maxWords: number | null = null;
  if (d.maxWords.trim()) {
    const n = Number(d.maxWords);
    if (!Number.isInteger(n) || n < 1 || n > 5000) return { ok: false, error: "max_words" };
    maxWords = n;
  }
  const forbidden = [...new Set(d.forbiddenTools)];
  if (d.expectedTool && d.expectedTool !== "none" && forbidden.includes(d.expectedTool)) return { ok: false, error: "conflict" };
  return {
    ok: true,
    body: {
      name: d.name.trim(),
      input: d.input.trim(),
      context_doc_ids: d.docs.map((doc) => doc.id),
      must_include: lines(d.mustInclude),
      must_not_include: lines(d.mustNotInclude),
      must_cite: d.mustCite,
      expected_tool: d.expectedTool,
      forbidden_tools: forbidden,
      max_words: maxWords,
      language: d.language,
      rubric: d.rubric.trim(),
    },
  };
}

/** How many checks a case has (the judge counts as one). */
export function checkCount(c: Pick<EvalCase, "must_include" | "must_not_include" | "must_cite" | "expected_tool" | "forbidden_tools" | "max_words" | "language" | "rubric">): number {
  return (
    c.must_include.length +
    c.must_not_include.length +
    (c.must_cite ? 1 : 0) +
    (c.expected_tool ? 1 : 0) +
    (c.forbidden_tools.length ? 1 : 0) +
    (c.max_words ? 1 : 0) +
    (c.language !== "any" ? 1 : 0) +
    (c.rubric ? 1 : 0)
  );
}

export function score(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

export function inFlight(runs: Pick<RunSummary, "status">[]): boolean {
  return runs.some((r) => r.status === "queued" || r.status === "running");
}

/** Cases that passed in the previous run and fail now: what the diff view calls out first. */
export function regressions(detail: Pick<RunDetail, "results" | "previous_results">): string[] {
  const before = detail.previous_results ?? {};
  return detail.results.filter((r) => !r.passed && before[r.case]?.passed).map((r) => r.case);
}

/** Failed cases first (new failures before old ones), then passes, keeping the set's order inside each group. */
export function orderResults(detail: Pick<RunDetail, "results" | "previous_results">): CaseResult[] {
  const fresh = new Set(regressions(detail));
  const rank = (r: CaseResult) => (fresh.has(r.case) ? 0 : r.passed ? 2 : 1);
  return detail.results.map((r, i) => ({ r, i })).sort((a, b) => rank(a.r) - rank(b.r) || a.i - b.i).map(({ r }) => r);
}

export function shortDate(iso: string, locale?: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** The set's pass mark between 0 and 100, from a text field. */
export function clampPercent(text: string, fallback: number): number {
  const n = Math.round(Number(text));
  return Number.isFinite(n) && text.trim() !== "" ? Math.min(100, Math.max(0, n)) : fallback;
}
