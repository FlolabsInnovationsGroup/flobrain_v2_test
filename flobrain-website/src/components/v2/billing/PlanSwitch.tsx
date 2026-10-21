"use client";

import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError, errorText } from "@/lib/v2/api";

import { describeChanges, priceLabel, toPricePlan, unitLabel, type ServerPlan, type SwitchPreview, type SwitchResult } from "./billing";
import { calculate, formatMoney, formatNumber, type Interval } from "./pricing";
import { Segmented } from "./Segmented";

type Props = {
  orgId: string;
  plans: ServerPlan[];
  currentCode: string | null;
  currentInterval: Interval;
  seatsUsed: number;
  checkout: "stripe" | "demo" | "off";
  canManage: boolean;
  locale: string;
  suggested?: string | null;
  onDone: (message: string) => void;
};

const segmentButton = (checked: boolean) =>
  `rounded-lg px-3 py-1.5 text-sm ${checked ? "bg-[color:var(--fb-v2-accent)] text-white" : "text-[color:var(--fb-v2-text-muted)] hover:text-[color:var(--fb-v2-text)]"}`;

/** Plans side by side for this team, which is cheaper, and a switch with a confirmation. */
export function PlanSwitch({ orgId, plans, currentCode, currentInterval, seatsUsed, checkout, canManage, locale, suggested, onDone }: Props) {
  const tr = useTr();
  const [interval, setPeriod] = useState<Interval>(currentInterval);
  const [seats, setSeats] = useState(String(Math.max(1, seatsUsed)));
  const [preview, setPreview] = useState<{ plan: ServerPlan; data: SwitchPreview } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const team = Math.max(1, Math.min(10000, Number(seats) || seatsUsed || 1));
  const calc = useMemo(() => calculate(plans.map(toPricePlan), team, interval), [plans, team, interval]);
  const comparison = calc.comparisons[0];
  const rows = Object.fromEntries(calc.plans.map((r) => [r.code, r]));
  const name = (code: string | null | undefined) => plans.find((p) => p.code === code)?.name ?? code ?? "";
  const money = (cents: number, currency = "USD") => formatMoney(cents, locale, currency);

  async function ask(plan: ServerPlan) {
    setError(null);
    setBusy(true);
    try {
      const data = await api.post<SwitchPreview>(`/orgs/${orgId}/billing/switch`, { plan: plan.code, interval, seats: plan.billing_unit === "per_workspace" ? undefined : team });
      setPreview({ plan, data });
    } catch (err) {
      setError(apiError(err).code === "no_change" ? tr("That is already your plan.") : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<SwitchResult>(`/orgs/${orgId}/billing/switch`, {
        plan: preview.plan.code,
        interval,
        seats: preview.plan.billing_unit === "per_workspace" ? undefined : team,
        confirm: true,
      });
      setPreview(null);
      if (res.mode === "stripe" && res.url) {
        window.location.assign(res.url);
        return;
      }
      onDone(res.mode === "demo" ? tr("Demo: your plan changed. No payment was taken.") : tr("Sent to Stripe. Your plan changes as soon as Stripe confirms it."));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented
          label={tr("Billing period")}
          value={interval}
          onChange={setPeriod}
          className="inline-flex gap-1 rounded-xl bg-[color:var(--fb-v2-surface)] p-1"
          buttonClassName={segmentButton}
          options={[
            { value: "month", label: tr("Monthly") },
            { value: "year", label: tr("Yearly") },
          ]}
        />
        <label className="flex items-center gap-2 text-sm">
          {tr("People")}
          <input className="v2-input w-24" type="number" min={Math.max(1, seatsUsed)} max={10000} value={seats} onChange={(e) => setSeats(e.target.value)} />
        </label>
        <Badge>{tr("Sample prices")}</Badge>
      </div>

      {comparison ? (
        <p className="mb-3 text-sm" aria-live="polite">
          {comparison.cheaper
            ? comparison.savingsPerYearCents > 0
              ? tr("For {n} people, {plan} is cheaper by {amount} a year.", { n: formatNumber(team, locale), plan: name(comparison.cheaper), amount: money(comparison.savingsPerYearCents) })
              : tr("For {n} people, only {plan} fits.", { n: formatNumber(team, locale), plan: name(comparison.cheaper) })
            : null}
          {comparison.breakEven ? ` ${tr("{plan} costs less from {n} people.", { plan: name(comparison.perWorkspace), n: formatNumber(comparison.breakEven, locale) })}` : ""}
        </p>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {plans.map((p) => {
          const row = rows[p.code];
          const current = p.code === currentCode && interval === currentInterval;
          const cheaper = comparison?.cheaper === p.code && (comparison.perSeat === p.code || comparison.perWorkspace === p.code);
          const workspace = p.billing_unit === "per_workspace";
          const unitPrice = row?.unitPriceCents ?? null;
          return (
            <div
              key={p.code}
              className={`rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ${current ? "ring-[color:var(--fb-v2-accent)]" : suggested === p.code ? "ring-2 ring-[color:var(--fb-v2-accent-strong)]" : "ring-[color:var(--fb-v2-border)]"}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-semibold">{p.name}</p>
                <Badge tone={workspace ? "accent" : "neutral"}>{unitLabel(p.billing_unit, tr)}</Badge>
                {cheaper ? <Badge tone="good">{tr("Cheaper for your team")}</Badge> : null}
              </div>
              <p className="mt-2 text-2xl font-semibold tabular-nums">{unitPrice === null ? tr("Not offered") : money(unitPrice, p.currency)}</p>
              <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                {workspace
                  ? interval === "year"
                    ? tr("for the workspace, per year, up to {n} people", { n: formatNumber(p.included_seats ?? 0, locale) })
                    : tr("for the workspace, per month, up to {n} people", { n: formatNumber(p.included_seats ?? 0, locale) })
                  : interval === "year"
                    ? tr("per seat, per year")
                    : tr("per seat, per month")}
              </p>
              {row?.available ? (
                <p className="mt-2 text-sm tabular-nums">{tr("Your team: {price}", { price: priceLabel(interval === "year" ? row.perYearCents : row.perMonthCents, interval, tr, locale, p.currency) })}</p>
              ) : row?.reason === "over_cap" ? (
                <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Fits up to {n} people.", { n: formatNumber(row.seatCap ?? 0, locale) })}</p>
              ) : null}
              {workspace && p.ai_allowance_per_workspace ? (
                <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} buddy answers a month for the whole workspace", { n: formatNumber(p.ai_allowance_per_workspace, locale) })}</p>
              ) : null}
              {current ? (
                <p className="mt-3 text-sm text-[color:var(--fb-v2-accent)]">{tr("(current)")}</p>
              ) : canManage && checkout !== "off" && row?.available ? (
                <Button className="mt-3" variant="outline" disabled={busy} onClick={() => ask(p)}>
                  {tr("Switch to {plan}", { plan: p.name })}
                </Button>
              ) : null}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Sample prices until pricing is final. We never charge for extra people without asking.")}</p>
      {!canManage ? <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Only the owner can change the plan.")}</p> : null}
      {canManage && checkout === "off" ? <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Checkout is not set up on this server.")}</p> : null}
      {error && !preview ? <Notice kind="error">{error}</Notice> : null}
      {preview ? (
        <ConfirmSwitch
          preview={preview.data}
          planName={preview.plan.name}
          checkout={checkout}
          busy={busy}
          error={error}
          locale={locale}
          onCancel={() => {
            setPreview(null);
            setError(null);
          }}
          onConfirm={confirm}
        />
      ) : null}
    </div>
  );
}

export function ConfirmSwitch({
  preview,
  planName,
  checkout,
  busy,
  error,
  locale,
  onCancel,
  onConfirm,
}: {
  preview: SwitchPreview;
  planName: string;
  checkout: "stripe" | "demo" | "off";
  busy: boolean;
  error: string | null;
  locale: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const tr = useTr();
  const lines = describeChanges(preview, tr, locale);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="switch-title">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-[color:var(--fb-v2-bg)] p-5 ring-1 ring-[color:var(--fb-v2-border)] sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <h2 id="switch-title" className="text-lg font-semibold">
            {tr("Switch to {plan}?", { plan: planName })}
          </h2>
          <button type="button" className="rounded p-1 hover:bg-[color:var(--fb-v2-border)]" aria-label={tr("Close")} onClick={onCancel}>
            <X size={18} aria-hidden />
          </button>
        </div>
        <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("This is exactly what changes:")}</p>
        <ul className="mt-3 list-disc space-y-1.5 ps-5 text-sm">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {checkout === "demo"
            ? tr("Demo: no payment is taken and no card is asked for.")
            : preview.proration === "stripe"
              ? tr("Stripe charges or credits the difference for the rest of this period on your next invoice.")
              : tr("You pay at checkout on Stripe.")}
        </p>
        {preview.sample ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Sample prices until pricing is final.")}</p> : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {tr("Cancel")}
          </Button>
          <Button onClick={onConfirm} disabled={busy} autoFocus>
            {tr("Confirm switch")}
          </Button>
        </div>
      </div>
    </div>
  );
}
