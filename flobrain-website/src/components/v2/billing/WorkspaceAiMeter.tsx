"use client";

import { barPercent, meterState } from "@/components/v2/growth/growth";
import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import type { AiIncluded } from "./billing";
import { formatNumber } from "./pricing";

/**
 * AI included in a per-workspace plan: one monthly pool of buddy answers for the whole workspace,
 * shared by everyone (the per-seat plans use growth/AiSeatMeter instead). Data comes from the
 * billing payload (`workspace_pricing.ai`), so it shows even when the `budgets` meter is off.
 */
export function WorkspaceAiMeter({ ai, sample, locale }: { ai: AiIncluded; sample: boolean; locale: string }) {
  const tr = useTr();
  const used = ai.used ?? 0;
  const pct = barPercent(used, ai.total);
  const exact = ai.total ? Math.round((100 * used) / ai.total) : 0;
  const status = meterState({ used, included_total: ai.total, projected: used });
  const fmt = (n: number) => formatNumber(n, locale);
  return (
    <section className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" aria-labelledby="ws-ai-meter-title">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="ws-ai-meter-title" className="font-semibold">
            {tr("AI included in your plan")}
          </h2>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} buddy answers a month for the whole workspace, shared by everyone.", { n: fmt(ai.total) })}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {sample ? <Badge>{tr("Sample numbers")}</Badge> : null}
          {status === "over" ? <Badge tone="bad">{tr("Over the included amount")}</Badge> : null}
        </div>
      </div>
      {ai.used === null || ai.used === undefined ? null : (
        <>
          <div
            className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-[color:var(--fb-v2-track)]"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-label={tr("{pct}% of the included AI answers used", { pct: exact })}
          >
            <div
              className="absolute inset-y-0 rounded-full"
              style={{ insetInlineStart: 0, width: `${pct}%`, background: status === "over" ? "var(--fb-v2-error)" : "var(--fb-v2-accent)" }}
              aria-hidden
            />
          </div>
          <p className="mt-2 text-sm tabular-nums">{tr("{used} of {total} used this month ({pct}%)", { used: fmt(used), total: fmt(ai.total), pct: exact })}</p>
        </>
      )}
      <p className="mt-3 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Counts answers made with FloBrain's AI. Answers on your own AI keys are not counted.")}
        {sample ? ` ${tr("Allowances are examples until pricing is final.")}` : ""}
      </p>
    </section>
  );
}
