"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

export type BudgetRow = {
  id: string;
  scope_type: "org" | "team" | "user";
  scope_id: string | null;
  scope_name: string;
  cap_amount: string;
  currency: string;
  on_exceed: "block" | "downgrade" | "alert_only";
  downgrade_model: string | null;
  alert_threshold: string;
  spent?: string;
  ratio?: number;
  state?: "ok" | "alert" | "exceeded";
};

export const ON_EXCEED: Record<string, string> = {
  block: "Stop platform AI",
  downgrade: "Switch to a cheaper model",
  alert_only: "Only alert",
};
export const SCOPES: Record<string, string> = { org: "Organization", team: "Team", user: "Member" };

export function money(amount: string | undefined, currency: string) {
  const value = Number(amount ?? 0);
  try {
    return value.toLocaleString(undefined, { style: "currency", currency, maximumFractionDigits: value < 1 ? 4 : 2 });
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** One budget: who it covers, spend against the limit as a bar, and what happens at 100%. */
export function BudgetMeter({ budget, actions }: { budget: BudgetRow; actions?: React.ReactNode }) {
  const tr = useTr();
  const ratio = Math.max(0, budget.ratio ?? 0);
  const pct = Math.round(ratio * 100);
  const threshold = Math.round(Number(budget.alert_threshold) * 100);
  const tone = budget.state === "exceeded" ? "bad" : budget.state === "alert" ? "waiting" : "good";
  const bar = budget.state === "exceeded" ? "var(--fb-v2-error)" : budget.state === "alert" ? "var(--fb-v2-waiting)" : "var(--fb-v2-success)";
  const stateLabel = budget.state === "exceeded" ? tr("Used up") : budget.state === "alert" ? tr("Over {n}%", { n: threshold }) : tr("On track");
  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{budget.scope_name}</p>
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr(SCOPES[budget.scope_type] ?? budget.scope_type)}. {tr("At 100%: {what}.", { what: tr(ON_EXCEED[budget.on_exceed] ?? budget.on_exceed) })}
            {budget.on_exceed === "downgrade" && budget.downgrade_model ? ` ${tr("Uses {model}.", { model: budget.downgrade_model })}` : ""}
          </p>
        </div>
        {budget.state ? <Badge tone={tone}>{stateLabel}</Badge> : null}
      </div>
      {budget.spent !== undefined ? (
        <>
          <div
            className="relative mt-3 h-2 overflow-hidden rounded-full bg-[color:var(--fb-v2-border)]"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.min(pct, 100)}
            aria-label={tr("{pct}% of the budget used", { pct })}
          >
            <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: bar }} />
            <div className="absolute inset-y-0 w-px bg-[color:var(--fb-v2-text-muted)]" style={{ insetInlineStart: `${Math.min(threshold, 100)}%` }} aria-hidden />
          </div>
          <p className="mt-2 text-sm tabular-nums">
            {tr("{spent} of {limit} this month ({pct}%)", { spent: money(budget.spent, budget.currency), limit: money(budget.cap_amount, budget.currency), pct })}
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm tabular-nums">{tr("Limit {limit} a month", { limit: money(budget.cap_amount, budget.currency) })}</p>
      )}
      {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
