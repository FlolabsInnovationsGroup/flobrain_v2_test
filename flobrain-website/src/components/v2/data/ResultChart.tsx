"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/v2/ui/button";
import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";

import { buildChart, formatValue, headlineValue, humanize, type Series } from "./chartData";
import styles from "./ResultChart.module.css";
import type { ChartSpec, Result } from "./types";

const TABLE_ROWS = 200;

function color(slot: number) {
  return slot < 0 ? "var(--data-other)" : `var(--data-s${slot})`;
}

export function DataTable({ result, caption }: { result: Result; caption?: string }) {
  const tr = useTr();
  const locale = useLocale();
  const rows = result.rows.slice(0, TABLE_ROWS);
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-[color:var(--fb-v2-border)]" tabIndex={0} role="region" aria-label={caption || tr("Result table")}>
      <table className="w-full border-collapse text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="sticky top-0 bg-[color:var(--fb-v2-raised)]">
          <tr>
            {result.columns.map((c) => (
              <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 text-start font-medium text-[color:var(--fb-v2-text-muted)]">
                {humanize(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-[color:var(--fb-v2-border)]">
              {row.map((value, j) => (
                <td key={j} className={`whitespace-nowrap px-3 py-1.5 ${typeof value === "number" ? "text-end tabular-nums" : "text-start"}`}>
                  {typeof value === "number" ? formatValue(value, locale) : value === null ? "" : String(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.rows.length > TABLE_ROWS || result.truncated ? (
        <p className="px-3 py-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Showing the first {n} rows.", { n: Math.min(result.rows.length, TABLE_ROWS) })}</p>
      ) : null}
    </div>
  );
}

function Legend({ series }: { series: Series[] }) {
  const tr = useTr();
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[color:var(--fb-v2-text-muted)]" aria-label={tr("Legend")}>
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span aria-hidden className={styles.swatch} style={{ background: color(s.slot) }} />
          {s.slot < 0 ? tr("Other") : s.label}
        </li>
      ))}
    </ul>
  );
}

type TipProps = { active?: boolean; label?: string | number; payload?: { dataKey?: string | number; value?: unknown }[] };

function Tip({ active, label, payload, series, locale }: TipProps & { series: Series[]; locale: string }) {
  const tr = useTr();
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-page)] px-3 py-2 text-xs text-[color:var(--fb-v2-text)] shadow">
      <p className="mb-1 font-medium">{String(label ?? "")}</p>
      {payload.map((p) => {
        const s = series.find((x) => x.key === p.dataKey);
        if (!s || p.value === null || p.value === undefined) return null;
        return (
          <p key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className={styles.swatch} style={{ background: color(s.slot) }} />
            <span className="text-[color:var(--fb-v2-text-muted)]">{s.slot < 0 ? tr("Other") : s.label}</span>
            <span className="ms-auto ps-3 tabular-nums">{formatValue(p.value, locale)}</span>
          </p>
        );
      })}
    </div>
  );
}

/** Answer chart: bar, line or a single number, always with a table view. */
export function ResultChart({ spec, result, title }: { spec: ChartSpec; result: Result; title: string }) {
  const tr = useTr();
  const locale = useLocale();
  const rtl = dirFor(locale) === "rtl";
  const [asTable, setAsTable] = useState(false);

  if (!result.rows.length) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No rows.")}</p>;

  if (spec.type === "number") {
    const value = headlineValue(spec, result);
    return (
      <figure className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-label={title}>
        <p className="text-4xl font-semibold tabular-nums">{formatValue(value, locale)}</p>
        <figcaption className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{humanize(spec.y[0] ?? "")}</figcaption>
      </figure>
    );
  }

  const chart = buildChart(spec, result);
  if (spec.type === "table" || !chart.data.length) return <DataTable result={result} caption={title} />;

  const tick = { fill: "var(--fb-v2-text-muted)", fontSize: 12 };
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke="var(--fb-v2-border)" />
      <XAxis dataKey="x" tickLine={false} axisLine={{ stroke: "var(--fb-v2-border)" }} tick={tick} reversed={rtl} minTickGap={12} />
      <YAxis
        tickLine={false}
        axisLine={false}
        width={52}
        tick={tick}
        orientation={rtl ? "right" : "left"}
        tickFormatter={(v) => formatValue(v, locale, true)}
      />
      <Tooltip
        cursor={spec.type === "bar" ? { fill: "var(--fb-v2-border)" } : { stroke: "var(--fb-v2-border-strong)" }}
        content={(props) => <Tip {...(props as unknown as TipProps)} series={chart.series} locale={locale} />}
      />
    </>
  );
  const dots = chart.data.length <= 24;
  const last = chart.data.length - 1;

  return (
    <figure className={`${styles.viz} rounded-xl bg-[color:var(--fb-v2-surface)] p-4`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        {chart.series.length >= 2 ? <Legend series={chart.series} /> : <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{humanize(chart.series[0]?.label ?? "")}</span>}
        <Button variant="ghost" className="text-xs" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? tr("Show chart") : tr("Show table")}
        </Button>
      </div>
      {asTable ? (
        <DataTable result={result} caption={title} />
      ) : (
        <div className="h-72" role="img" aria-label={tr("{title}. Use Show table for the numbers.", { title })}>
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 240 }}>
            {spec.type === "line" ? (
              <LineChart data={chart.data} margin={{ top: 8, right: 24, bottom: 0, left: 24 }}>
                {axes}
                {chart.series.map((s) => (
                  <Line
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    stroke={color(s.slot)}
                    strokeWidth={2}
                    dot={dots ? { r: 4, strokeWidth: 2, stroke: "var(--fb-v2-surface)", fill: color(s.slot) } : false}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--fb-v2-surface)" }}
                    connectNulls
                    isAnimationActive={false}
                  >
                    {chart.series.length >= 2 ? (
                      <LabelList
                        dataKey={s.key}
                        content={(p) => {
                          const { x, y, index } = p as { x?: number; y?: number; index?: number };
                          if (index !== last || x === undefined || y === undefined) return null;
                          return (
                            <text x={x} y={y - 10} textAnchor="middle" fontSize={11} fill="var(--fb-v2-text-muted)">
                              {s.slot < 0 ? tr("Other") : s.label}
                            </text>
                          );
                        }}
                      />
                    ) : null}
                  </Line>
                ))}
              </LineChart>
            ) : (
              <BarChart data={chart.data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }} barGap={2} barCategoryGap="20%">
                {axes}
                {chart.series.map((s) => (
                  <Bar key={s.key} dataKey={s.key} fill={color(s.slot)} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
      {chart.folded ? (
        <figcaption className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
          {spec.series ? tr("{n} smaller groups are combined as Other.", { n: chart.folded }) : tr("{n} more columns are in the table view.", { n: chart.folded })}
        </figcaption>
      ) : null}
    </figure>
  );
}
