"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useTr } from "@/i18n/phrases";

import { score, shortDate, type TrendPoint } from "./evals";

type Point = TrendPoint & { label: string; n: number };

/*
 * One series (the score) on a 0-100 axis, the pass mark as a dashed reference line. A run under the
 * pass mark is a rose square (status colour plus a different shape and a text label in the legend
 * and tooltip), so colour never carries the meaning alone. Time runs left to right in every language.
 */
function Dot(props: { cx?: number; cy?: number; payload?: Point; index?: number }) {
  const { cx, cy, payload, index } = props;
  if (cx === undefined || cy === undefined || !payload) return <g key={`d-${index}`} />;
  if (payload.passed === false) {
    return <rect key={`d-${index}`} x={cx - 5} y={cy - 5} width={10} height={10} rx={2} fill="var(--fb-v2-error)" stroke="var(--fb-v2-surface)" strokeWidth={2} />;
  }
  return <circle key={`d-${index}`} cx={cx} cy={cy} r={4} fill="var(--fb-v2-accent)" stroke="var(--fb-v2-surface)" strokeWidth={2} />;
}

export function ScoreTrend({ trend, threshold }: { trend: TrendPoint[]; threshold: number }) {
  const tr = useTr();
  const data: Point[] = trend.map((p, i) => ({ ...p, n: i + 1, label: shortDate(p.at) }));
  const trigger = (t: TrendPoint["triggered_by"]) => (t === "gate" ? tr("Gate check") : t === "schedule" ? tr("Scheduled") : tr("Run by hand"));
  if (!data.length) return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No runs yet. Run the set to see its score here.")}</p>;
  return (
    <figure className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[color:var(--fb-v2-text-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0.5 w-4 rounded-full bg-[color:var(--fb-v2-accent)]" />
          {tr("Score")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block w-4 border-t-2 border-dashed border-[color:var(--fb-v2-text-muted)]" />
          {tr("Pass mark {n}%", { n: threshold })}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-[color:var(--fb-v2-error)]" />
          {tr("Below the pass mark")}
        </span>
      </figcaption>
      <div dir="ltr" className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--fb-v2-border)" />
            <XAxis dataKey="n" tickFormatter={(n: number) => data[n - 1]?.label ?? ""} tickLine={false} axisLine={false} minTickGap={16} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} axisLine={false} width={32} tick={{ fill: "var(--fb-v2-text-muted)", fontSize: 12 }} />
            <ReferenceLine y={threshold} stroke="var(--fb-v2-text-muted)" strokeDasharray="4 4" />
            <Tooltip
              cursor={{ stroke: "var(--fb-v2-border-strong)" }}
              content={({ active, payload }) => {
                const p = active && payload?.length ? (payload[0].payload as Point) : null;
                if (!p) return null;
                return (
                  <div className="rounded-lg border border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-page)] px-3 py-2 text-xs text-[color:var(--fb-v2-text)]">
                    <p className="text-[color:var(--fb-v2-text-muted)]">{p.label} · {p.version}</p>
                    <p className="mt-0.5 font-mono text-sm tabular-nums">{score(p.score)}</p>
                    <p className="mt-0.5">{p.passed === false ? tr("Below the pass mark") : tr("Passed")} · {trigger(p.triggered_by)}</p>
                  </div>
                );
              }}
            />
            <Line type="monotone" dataKey="score" name={tr("Score")} stroke="var(--fb-v2-accent)" strokeWidth={2} dot={Dot} activeDot={{ r: 5, stroke: "var(--fb-v2-surface)", strokeWidth: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Show as a table")}</summary>
        <div className="mt-2 max-h-64 overflow-auto">
          <table className="w-full">
            <thead className="text-[color:var(--fb-v2-text-muted)]">
              <tr>
                <th className="py-1 text-start font-medium">{tr("Date")}</th>
                <th className="py-1 text-start font-medium">{tr("Version")}</th>
                <th className="py-1 text-start font-medium">{tr("Started by")}</th>
                <th className="py-1 text-end font-medium">{tr("Score")}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.run} className="border-t border-[color:var(--fb-v2-border)]">
                  <td className="py-1">{p.label}</td>
                  <td className="py-1">{p.version}</td>
                  <td className="py-1">{trigger(p.triggered_by)}</td>
                  <td className="py-1 text-end tabular-nums">
                    {score(p.score)} {p.passed === false ? <span className="text-[color:var(--fb-v2-error)]">({tr("below")})</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
