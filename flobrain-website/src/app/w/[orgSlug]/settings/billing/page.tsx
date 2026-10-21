"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Plan = { id: string; code: string; name: string; price_cents: number; currency: string; interval: string; entitlements: { flags?: string[]; limits?: Record<string, number> } };
type Line = { period: string; metric: string; quantity: string; unit_price: string; amount: string };
type Billing = {
  plan: Plan | null;
  status: string;
  seats: number | null;
  seats_used: number;
  current_period_end: string | null;
  usage_this_month: { platform_cost: string; platform_events_unpriced: number; byok_events: number; byok_markup: string };
  checkout: "stripe" | "demo" | "off";
  can_manage: boolean;
  plans: Plan[];
  invoice_lines: Line[];
  has_billing_account: boolean;
};

/** Subscription states from the API, shown as words. Unknown ones show as they come. */
const STATUS: Record<string, string> = { trialing: "Trial", active: "Active", past_due: "Past due", canceled: "Canceled", none: "No subscription" };
const METRIC: Record<string, string> = { seats: "Seats", ai_platform_cost: "Platform AI at cost", render_gpu_seconds: "Video rendering (GPU seconds)" };

function money(amount: number | string, currency = "USD") {
  const value = typeof amount === "string" ? Number(amount) : amount;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {note ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{note}</p> : null}
    </div>
  );
}

function Invoices({ lines }: { lines: Line[] }) {
  const tr = useTr();
  const periods = [...new Set(lines.map((l) => l.period))];
  return (
    <div className="space-y-4">
      {periods.map((period) => {
        const rows = lines.filter((l) => l.period === period);
        const total = rows.reduce((sum, l) => sum + Number(l.amount), 0);
        return (
          <div key={period} className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
            <table className="w-full text-sm">
              <caption className="px-4 pt-3 text-start font-medium">{period}</caption>
              <thead className="text-[color:var(--fb-v2-text-muted)]">
                <tr>
                  <th className="px-4 py-2 text-start font-normal">{tr("Item")}</th>
                  <th className="px-4 py-2 text-end font-normal">{tr("Quantity")}</th>
                  <th className="px-4 py-2 text-end font-normal">{tr("Unit price")}</th>
                  <th className="px-4 py-2 text-end font-normal">{tr("Amount")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => (
                  <tr key={l.metric} className="border-t border-[color:var(--fb-v2-border)]">
                    <td className="px-4 py-2">{METRIC[l.metric] ? tr(METRIC[l.metric]) : l.metric}</td>
                    <td className="px-4 py-2 text-end tabular-nums">{Number(l.quantity).toLocaleString()}</td>
                    <td className="px-4 py-2 text-end tabular-nums">{Number(l.unit_price).toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                    <td className="px-4 py-2 text-end tabular-nums">{money(l.amount)}</td>
                  </tr>
                ))}
                <tr className="border-t border-[color:var(--fb-v2-border)] font-semibold">
                  <td className="px-4 py-2" colSpan={3}>
                    {tr("Total")}
                  </td>
                  <td className="px-4 py-2 text-end tabular-nums">{money(total)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense>
      <BillingScreen />
    </Suspense>
  );
}

function BillingScreen() {
  const tr = useTr();
  const router = useRouter();
  const params = useSearchParams();
  const { orgId } = useAccess();
  const { data, state, error, reload } = useOrgData<Billing>(orgId, "/billing");
  const [seats, setSeats] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function go(path: string, body?: unknown) {
    setMessage(null);
    try {
      const res = await api.post<{ mode: "stripe" | "demo"; url: string }>(`/orgs/${orgId}/billing/${path}`, body);
      if (res.mode === "stripe") window.location.assign(res.url);
      else router.push(res.url);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const done = params.get("checkout") === "done";
  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Billing")}
        intro={tr("Your plan, seats, and this month's AI use. AI you run on your own keys is charged at zero markup.")}
        action={
          data?.can_manage && data.checkout !== "off" && (data.has_billing_account || data.checkout === "demo") && data.plan ? (
            <Button variant="outline" onClick={() => go("portal")}>
              {tr("Manage billing")}
            </Button>
          ) : null
        }
      />
      {done ? <Notice kind="ok">{tr("Thanks. Your plan is updated as soon as the payment is confirmed.")}</Notice> : null}
      {params.get("checkout") === "demo" ? <Notice kind="ok">{tr("Demo: your plan changed. No payment was taken.")}</Notice> : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={state} error={error} onRetry={reload}>
        {data ? (
          <>
            {data.checkout === "demo" ? <Notice>{tr("Demo: checkout here is pretend. No payment is taken and no card is asked for.")}</Notice> : null}
            <div className="mb-6 flex flex-wrap items-center gap-3">
              <p className="text-lg font-semibold">{data.plan ? data.plan.name : tr("No plan yet")}</p>
              <Badge tone={data.status === "active" ? "good" : data.status === "past_due" ? "waiting" : "neutral"}>{STATUS[data.status] ? tr(STATUS[data.status]) : data.status}</Badge>
              {data.current_period_end ? <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Renews {date}", { date: when(data.current_period_end) })}</span> : null}
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label={tr("Seats used")} value={data.seats ? tr("{used} of {seats}", { used: data.seats_used, seats: data.seats }) : String(data.seats_used)} />
              <Stat
                label={tr("Platform AI this month")}
                value={`$${data.usage_this_month.platform_cost}`}
                note={data.usage_this_month.platform_events_unpriced ? tr("{n} calls had no price yet", { n: data.usage_this_month.platform_events_unpriced }) : tr("At cost")}
              />
              <Stat label={tr("Calls on members' own keys")} value={String(data.usage_this_month.byok_events)} note={tr("Markup ${amount}", { amount: data.usage_this_month.byok_markup })} />
            </div>
            {!data.plan ? (
              <p className="mt-6 text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("Without a plan, every feature your admins switch on is available. Plans and checkout are set up by FloBrain.")}
              </p>
            ) : null}

            {data.plans.length ? (
              <Section title={tr("Plans")}>
                {data.can_manage && data.checkout !== "off" ? (
                  <label className="mb-3 flex items-center gap-2 text-sm">
                    {tr("Seats")}
                    <input
                      className="v2-input w-24"
                      type="number"
                      min={1}
                      max={10000}
                      placeholder={String(Math.max(1, data.seats_used))}
                      value={seats}
                      onChange={(e) => setSeats(e.target.value)}
                    />
                  </label>
                ) : null}
                <div className="grid gap-3 sm:grid-cols-3">
                  {data.plans.map((p) => {
                    const current = data.plan?.code === p.code && data.status !== "canceled";
                    return (
                      <div key={p.code} className={`rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ${current ? "ring-[color:var(--fb-v2-accent)]" : "ring-[color:var(--fb-v2-border)]"}`}>
                        <p className="font-semibold">{p.name}</p>
                        <p className="mt-1 text-2xl font-semibold">{money(p.price_cents / 100, p.currency)}</p>
                        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{p.interval === "year" ? tr("per seat, per year") : tr("per seat, per month")}</p>
                        <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                          {tr("{n} features.", { n: p.entitlements.flags?.length ?? 0 })} {p.entitlements.limits?.seats ? tr("Up to {n} seats.", { n: p.entitlements.limits.seats }) : ""}
                        </p>
                        {current ? (
                          <p className="mt-3 text-sm text-[color:var(--fb-v2-accent)]">{tr("(current)")}</p>
                        ) : data.can_manage && data.checkout !== "off" ? (
                          <Button className="mt-3" variant="outline" onClick={() => go("checkout", { plan: p.code, seats: seats ? Number(seats) : 0 })}>
                            {data.checkout === "demo" ? tr("Choose (demo checkout)") : tr("Choose")}
                          </Button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                {!data.can_manage ? <p className="mt-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Only the owner can change the plan.")}</p> : null}
                {data.can_manage && data.checkout === "off" ? <p className="mt-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Checkout is not set up on this server.")}</p> : null}
              </Section>
            ) : null}

            <Section title={tr("Invoice lines")}>
              {data.invoice_lines.length ? <Invoices lines={data.invoice_lines} /> : <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No invoice lines yet.")}</p>}
            </Section>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
