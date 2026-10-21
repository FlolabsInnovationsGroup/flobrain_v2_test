"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useTr } from "@/i18n/phrases";

import { shortDay, type QualityStats } from "./crew";

/*
 * Series colours (checked with the dataviz validator: lightness band, chroma, colour-blind and
 * normal-vision separation, 3:1 contrast). Dark steps against the dark surface, light steps against
 * white. Scoped to this chart so the shared tokens stay untouched.
 */
const SERIES_CSS = `
.crew-trend { --crew-s1: #7c6bff; --crew-s2: #139fc4; --crew-s3: #cc34ff; }
.light .crew-trend { --crew-s1: #5b4ae6; --crew-s2: #0891b2; --crew-s3: #a21caf; }
`;

const SERIES = [
  { key: "answers", label: "Answers", color: "var(--crew-s1)" },
  { key: "helpful", label: "Rated helpful", color: "var(--crew-s2)" },
  { key: "not_helpful", label: "Rated not helpful", color: "var(--crew-s3)" },
] as const;

/** Daily answers and ratings: three counts on one axis, thin lines, legend above, table below. */
export function QualityTrend({ trend }: { trend: QualityStats["trend"] }) {
  const tr = useTr();
  const data = trend.map((d) => ({ ...d, label: shortDay(d.day) }));
  return (
    <figure className="crew-trend rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <style>{SERIES_CSS}</style>
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[color:var(--fb-v2-text-muted)]">
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 rounded-full" style={{ background: s.color }} />
            {tr(s.label)}
          </span>
        ))}
      </figcaption>
      {/* Time runs left to right in every language. */}
      <div dir="ltr" className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 240 }}>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--fb-v2-border)" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={16} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={32} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
            <Tooltip
              cursor={{ stroke: "var(--fb-v2-border-strong)" }}
              contentStyle={{ background: "var(--fb-v2-page)", border: "1px solid var(--fb-v2-border)", borderRadius: 8, color: "var(--fb-v2-text)" }}
              labelStyle={{ color: "var(--fb-v2-text-muted)" }}
            />
            {SERIES.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={tr(s.label)}
                stroke={s.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, stroke: "var(--fb-v2-surface)", strokeWidth: 2 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Show as a table")}</summary>
        <div className="mt-2 max-h-64 overflow-auto">
          <table className="w-full text-start">
            <thead className="text-[color:var(--fb-v2-text-muted)]">
              <tr>
                <th className="py-1 text-start font-medium">{tr("Day")}</th>
                {SERIES.map((s) => (
                  <th key={s.key} className="py-1 text-end font-medium">
                    {tr(s.label)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.day} className="border-t border-[color:var(--fb-v2-border)]">
                  <td className="py-1">{d.label}</td>
                  <td className="py-1 text-end tabular-nums">{d.answers}</td>
                  <td className="py-1 text-end tabular-nums">{d.helpful}</td>
                  <td className="py-1 text-end tabular-nums">{d.not_helpful}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
