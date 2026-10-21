"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useOrgData } from "@/lib/v2/useOrgData";

import { barPercent, meterState, type Allowance } from "./growth";

/**
 * AI included per seat: buddy answers used this month against the plan's allowance, the month-end
 * projection, your own use and (for admins) use per person. Reads ``GET /orgs/{org}/ai-allowance``
 * (flag ``budgets``). Renders nothing when that endpoint is off or not allowed.
 * Mount it on the usage settings page or a billing page: ``<AiSeatMeter orgId={orgId} />``.
 */
export function AiSeatMeter({ orgId, showPeople = true }: { orgId: string | null; showPeople?: boolean }) {
  const tr = useTr();
  const { data, state } = useOrgData<Allowance>(orgId, "/ai-allowance");
  if (state !== "ready" || !data) return null;
  const status = meterState(data);
  const used = barPercent(data.used, data.included_total);
  const projected = barPercent(data.projected, data.included_total);
  const fill = status === "over" ? "var(--fb-v2-error)" : "var(--fb-v2-accent)";
  const fmt = (n: number) => n.toLocaleString();
  const people = showPeople ? (data.people ?? []).slice(0, 12) : [];
  const top = Math.max(1, ...people.map((p) => p.used));
  return (
    <section className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-labelledby="ai-seat-meter-title">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="ai-seat-meter-title" className="font-semibold">
            {tr("AI included in your plan")}
          </h2>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("{n} buddy answers per seat each month, {seats} seats.", { n: fmt(data.included_per_seat), seats: data.seats })}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {data.sample ? <Badge>{tr("Sample numbers")}</Badge> : null}
          {status === "over" ? <Badge tone="bad">{tr("Over the included amount")}</Badge> : null}
          {status === "trending" ? <Badge tone="neutral">{tr("On track to go over")}</Badge> : null}
        </div>
      </div>
      <div
        className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-[color:var(--fb-v2-track)]"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={used}
        aria-label={tr("{pct}% of the included AI answers used", { pct: data.used_pct })}
      >
        <div className="absolute inset-y-0 rounded-full bg-[color:var(--fb-v2-accent-soft)]" style={{ insetInlineStart: 0, width: `${projected}%` }} aria-hidden />
        <div className="absolute inset-y-0 rounded-full" style={{ insetInlineStart: 0, width: `${used}%`, background: fill }} aria-hidden />
      </div>
      <p className="mt-2 text-sm tabular-nums">
        {tr("{used} of {total} used this month ({pct}%)", { used: fmt(data.used), total: fmt(data.included_total), pct: data.used_pct })}
      </p>
      <p className="text-sm tabular-nums text-[color:var(--fb-v2-text-muted)]">
        {tr("At this pace: about {n} by the end of the month ({pct}%).", { n: fmt(data.projected), pct: data.projected_pct })}
      </p>
      <p className="mt-1 text-sm tabular-nums">
        {tr("You: {n} answers this month.", { n: fmt(data.mine.used) })}
      </p>
      {people.length ? (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Use per person")}</summary>
          <ul className="mt-2 flex flex-col gap-1.5">
            {people.map((p) => (
              <li key={p.user_id ?? p.name} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2">
                <span className="truncate">{p.user_id === "private" ? tr("People who keep their insights personal") : p.name || tr("Unknown")}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-[color:var(--fb-v2-track)]" aria-hidden>
                  <span className="block h-full rounded-full bg-[color:var(--fb-v2-accent)]" style={{ width: `${barPercent(p.used, top)}%` }} />
                </span>
                <span className="tabular-nums">{fmt(p.used)}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="mt-3 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Counts answers made with FloBrain's AI. Answers on your own AI keys are not counted.")}
        {data.sample ? ` ${tr("Allowances are examples until pricing is final.")}` : ""}
      </p>
    </section>
  );
}
