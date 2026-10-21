import type { ChartSpec, Result } from "./types";

/** At most three colored series (the validated palette); the rest fold into "Other". */
export const MAX_SERIES = 3;
export const OTHER = "__other__";

export type Series = { key: string; label: string; slot: number };
export type Point = Record<string, string | number | null>;
export type ChartData = { data: Point[]; series: Series[]; folded: number };

export function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function label(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  return String(value);
}

/** Rows to recharts points. With a series column the rows are pivoted, one key per series value. */
export function buildChart(spec: ChartSpec, result: Result): ChartData {
  const { columns, rows } = result;
  const xi = spec.x ? columns.indexOf(spec.x) : -1;
  if (xi < 0 || (spec.type !== "bar" && spec.type !== "line")) return { data: [], series: [], folded: 0 };
  const ys = spec.y.map((c) => columns.indexOf(c)).filter((i) => i >= 0);
  if (!ys.length) return { data: [], series: [], folded: 0 };

  const si = spec.series ? columns.indexOf(spec.series) : -1;
  if (si < 0) {
    const kept = ys.slice(0, MAX_SERIES);
    const series = kept.map((i, n) => ({ key: `s${n}`, label: columns[i], slot: n }));
    const data = rows.map((row) => {
      const point: Point = { x: label(row[xi]) };
      kept.forEach((i, n) => (point[`s${n}`] = toNumber(row[i])));
      return point;
    });
    return { data, series, folded: ys.length - kept.length };
  }

  const yi = ys[0];
  const totals = new Map<string, number>();
  for (const row of rows) totals.set(label(row[si]), (totals.get(label(row[si])) ?? 0) + (toNumber(row[yi]) ?? 0));
  const byTotal = [...totals.keys()].sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0));
  const many = byTotal.length > MAX_SERIES;
  // Slots follow the entity's name, not its rank, so a series keeps its color when numbers change.
  const kept = byTotal.slice(0, many ? MAX_SERIES - 1 : MAX_SERIES).sort((a, b) => a.localeCompare(b));
  const keyOf = new Map(kept.map((name, n) => [name, `s${n}`]));
  const series: Series[] = kept.map((name, n) => ({ key: `s${n}`, label: name, slot: n }));
  if (many) series.push({ key: OTHER, label: "Other", slot: -1 });

  const points = new Map<string, Point>();
  for (const row of rows) {
    const x = label(row[xi]);
    const point = points.get(x) ?? { x };
    points.set(x, point);
    const key = keyOf.get(label(row[si])) ?? OTHER;
    const value = toNumber(row[yi]);
    if (value !== null) point[key] = ((point[key] as number | null | undefined) ?? 0) + value;
  }
  const data = [...points.values()].map((p) => {
    for (const s of series) if (!(s.key in p)) p[s.key] = null;
    return p;
  });
  return { data, series, folded: many ? byTotal.length - kept.length : 0 };
}

/** The single value of a "number" chart, or null. */
export function headlineValue(spec: ChartSpec, result: Result): number | string | null {
  const col = spec.y[0];
  const i = col ? result.columns.indexOf(col) : -1;
  if (i < 0 || !result.rows.length) return null;
  const value = result.rows[0][i];
  return toNumber(value) ?? (value === null || value === undefined ? null : String(value));
}

export function formatValue(value: unknown, locale: string, compact = false): string {
  const n = toNumber(value);
  if (n === null) return value === null || value === undefined ? "" : String(value);
  return new Intl.NumberFormat(locale, compact ? { notation: "compact", maximumFractionDigits: 1 } : { maximumFractionDigits: 2 }).format(n);
}

/** A column name as people read it: "budget_left" -> "Budget left". */
export function humanize(name: string): string {
  const text = name.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : name;
}
