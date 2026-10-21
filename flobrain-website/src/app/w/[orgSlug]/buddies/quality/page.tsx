"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { activeFirst, compact, duration, money, percent, reasonLabel, type QualityStats } from "@/components/v2/crew/crew";
import { QualityTrend } from "@/components/v2/crew/QualityTrend";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { NoAccess } from "@/components/v2/states";
import { PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

const WINDOWS = [7, 30] as const;

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{note}</p> : null}
    </div>
  );
}

export default function BuddyQualityPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const [days, setDays] = useState<(typeof WINDOWS)[number]>(7);
  const allowed = has(access, "pulse.view") || has(access, "ai.usage.view");
  const { data, state, error, reload } = useOrgData<QualityStats>(orgId, allowed ? `/buddies/quality?days=${days}` : null);

  if (access && !allowed) return <NoAccess />;
  const rows = data ? activeFirst(data.buddies) : [];
  const totals = data?.totals;

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Buddy quality")}
        intro={tr("How each buddy is doing: answers, what people rated, approvals and cost. Numbers only; no messages are shown.")}
        action={
          <div role="group" aria-label={tr("Time range")} className="inline-flex rounded-lg p-0.5 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                aria-pressed={days === w}
                onClick={() => setDays(w)}
                className="rounded-md px-3 py-1.5 text-sm font-medium text-[color:var(--fb-v2-text-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)] aria-pressed:bg-[color:var(--fb-v2-accent)] aria-pressed:text-white"
              >
                {tr("{n} days", { n: w })}
              </button>
            ))}
          </div>
        }
      />
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data && totals ? (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label={tr("Answers")} value={compact(totals.answers)} />
              <Stat label={tr("Rated helpful")} value={percent(totals.helpful_rate)} note={tr("{n} ratings", { n: totals.ratings })} />
              <Stat
                label={tr("Actions approved")}
                value={`${totals.approved}/${totals.proposed}`}
                note={tr("{n} rejected", { n: totals.rejected })}
              />
              <Stat label={tr("Routed by Flo")} value={compact(data.routing.decisions)} note={tr("questions Flo handed on")} />
            </div>

            <Section title={tr("Daily trend")}>
              <QualityTrend trend={data.trend} />
            </Section>

            <Section title={tr("By buddy")}>
              <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
                <table className="w-full min-w-[56rem] text-sm">
                  <caption className="sr-only">{tr("Quality numbers for each buddy")}</caption>
                  <thead className="text-[color:var(--fb-v2-text-muted)]">
                    <tr>
                      <th scope="col" className="px-4 py-2 text-start font-medium">{tr("Buddy")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Answers")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Helpful")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Approved")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Rejected")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Median time")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("With sources")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Tokens")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("Cost")}</th>
                      <th scope="col" className="px-3 py-2 text-end font-medium">{tr("From Flo")}</th>
                      <th scope="col" className="px-4 py-2 text-start font-medium">{tr("Top reason")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t border-[color:var(--fb-v2-border)]">
                        <th scope="row" className="px-4 py-2 text-start font-medium">
                          <Link href={`/w/${orgSlug}/buddies/${r.id}`} className="hover:underline">
                            {r.name}
                          </Link>
                        </th>
                        <td className="px-3 py-2 text-end tabular-nums">{r.answers}</td>
                        <td className="px-3 py-2 text-end tabular-nums">
                          {percent(r.helpful_rate)}
                          {r.ratings ? <span className="ms-1 text-xs text-[color:var(--fb-v2-text-muted)]">({r.ratings})</span> : null}
                        </td>
                        <td className="px-3 py-2 text-end tabular-nums">
                          {r.approvals.approved}
                          {r.approvals.waiting ? (
                            <span className="ms-1 text-xs text-[color:var(--fb-v2-waiting)]">{tr("+{n} waiting", { n: r.approvals.waiting })}</span>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-end tabular-nums">{r.approvals.rejected}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{duration(r.median_latency_ms)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{percent(r.with_sources_rate)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{compact(r.tokens)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{money(r.cost)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{percent(r.routing_share)}</td>
                        <td className="px-4 py-2 text-start text-[color:var(--fb-v2-text-muted)]">
                          {r.top_reasons[0] ? `${tr(reasonLabel(r.top_reasons[0].reason))} (${r.top_reasons[0].count})` : "–"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
                {tr("A dash means no data yet. Time and sources are measured on replies sent from FloBrain's chat.")}
              </p>
            </Section>

            <Section title={tr("Why answers were not helpful")}>
              {data.reasons.length ? (
                <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
                  {data.reasons.map((r) => (
                    <li key={r.reason} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                      <span>{tr(reasonLabel(r.reason))}</span>
                      <span className="tabular-nums text-[color:var(--fb-v2-text-muted)]">{r.count}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nobody gave a reason in this period.")}</p>
              )}
            </Section>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
