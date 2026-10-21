/** Types for the billing API (workspace pricing, flag `workspace_pricing`) and pure helpers for the
 * billing page: server plan rows to the shared price math, and the "what changes" sentences. */

import { formatMoney, formatNumber, type BillingUnit, type Interval, type PricePlan } from "./pricing";

export type ServerPlan = {
  id: string;
  code: string;
  name: string;
  price_cents: number;
  currency: string;
  interval: string;
  entitlements: { flags?: string[]; limits?: Record<string, number> };
  billing_unit?: BillingUnit;
  included_seats?: number | null;
  overage_policy?: "block" | "prompt_upgrade";
  ai_allowance_per_workspace?: number | null;
  price_monthly_cents?: number | null;
  price_yearly_cents?: number | null;
  tier?: string;
  sample?: boolean;
};

export type AiIncluded = { basis: "per_seat" | "per_workspace"; per_seat: number | null; total: number; used?: number | null };

export type Side = {
  plan: string;
  name: string;
  billing_unit: BillingUnit;
  interval: Interval;
  seats: number;
  seat_cap: number | null;
  per_month_cents: number | null;
  per_year_cents: number | null;
  charge_cents: number | null;
  currency: string;
  ai: AiIncluded;
  overage_policy: string;
};

export type Change = { key: "plan" | "billing_unit" | "interval" | "seats" | "charge_cents" | "ai" | "seat_cap"; from: unknown; to: unknown };

export type SwitchPreview = { preview?: boolean; from: Side | null; to: Side; changes: Change[]; proration: "stripe" | "none"; sample: boolean };

export type SwitchResult = SwitchPreview & { mode: "stripe" | "demo"; status?: "pending" | "applied"; url?: string };

export type Invoice = {
  id: string;
  number: string;
  status: string;
  amount_cents: number;
  currency: string;
  plan: string;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
  url: string;
  demo: boolean;
};

export type SeatStatus = { unit: BillingUnit | null; limit: number | null; used: number; policy: string; upgrade_to: string | null; plan: string | null; plan_name: string | null };

export type WorkspacePricing = {
  enabled: true;
  sample: boolean;
  interval: Interval | null;
  seat_status: SeatStatus;
  ai: AiIncluded | null;
  price: Side | null;
  invoices: Invoice[];
};

/** A server plan row as input for the shared calculator (pricing.ts). */
export function toPricePlan(p: ServerPlan): PricePlan {
  const unit: BillingUnit = p.billing_unit ?? "per_seat";
  const month = p.price_monthly_cents !== undefined ? p.price_monthly_cents : p.interval === "year" ? null : p.price_cents;
  const year = p.price_yearly_cents !== undefined ? p.price_yearly_cents : p.interval === "year" ? p.price_cents : null;
  return {
    code: p.code,
    name: p.name,
    billingUnit: unit,
    monthCents: month,
    yearCents: year,
    seatCap: unit === "per_workspace" ? (p.included_seats ?? null) : (p.entitlements.limits?.seats ?? null),
    tier: p.tier || p.code,
    aiPerSeat: null,
    aiPerWorkspace: p.ai_allowance_per_workspace ?? null,
  };
}

type Tr = (text: string, vars?: Record<string, string | number>) => string;

export function unitLabel(unit: BillingUnit | null | undefined, tr: Tr): string {
  return unit === "per_workspace" ? tr("Per workspace") : tr("Per person");
}

export function priceLabel(cents: number | null, interval: Interval, tr: Tr, locale: string, currency = "USD"): string {
  if (cents === null) return tr("Not offered");
  const money = formatMoney(cents, locale, currency);
  return interval === "year" ? tr("{amount} a year", { amount: money }) : tr("{amount} a month", { amount: money });
}

function aiLabel(ai: AiIncluded, tr: Tr, locale: string): string {
  if (ai.basis === "per_workspace") return tr("{n} buddy answers a month for the whole workspace", { n: formatNumber(ai.total, locale) });
  return tr("{n} buddy answers per person ({total} a month)", { n: formatNumber(ai.per_seat ?? 0, locale), total: formatNumber(ai.total, locale) });
}

function seatsLabel(side: Side, tr: Tr, locale: string): string {
  return side.billing_unit === "per_workspace" ? tr("up to {n} people", { n: formatNumber(side.seats, locale) }) : tr("{n} seats", { n: formatNumber(side.seats, locale) });
}

/** One sentence per change, in the order the server sends them. Used by the confirmation. */
export function describeChanges(preview: SwitchPreview, tr: Tr, locale: string): string[] {
  const { from, to } = preview;
  if (!from) {
    return [
      tr("You start on {plan}, {unit}, billed {interval}.", { plan: to.name, unit: unitLabel(to.billing_unit, tr).toLowerCase(), interval: to.interval === "year" ? tr("yearly") : tr("monthly") }),
      tr("Price: {price}.", { price: priceLabel(to.charge_cents, to.interval, tr, locale, to.currency) }),
      tr("AI included: {ai}.", { ai: aiLabel(to.ai, tr, locale) }),
    ];
  }
  const out: string[] = [];
  for (const change of preview.changes) {
    if (change.key === "plan") out.push(tr("Plan: {from} becomes {to}.", { from: from.name, to: to.name }));
    if (change.key === "billing_unit") out.push(tr("Billing: {from} becomes {to}.", { from: unitLabel(from.billing_unit, tr).toLowerCase(), to: unitLabel(to.billing_unit, tr).toLowerCase() }));
    if (change.key === "interval") out.push(tr("Billed: {from} becomes {to}.", { from: from.interval === "year" ? tr("yearly") : tr("monthly"), to: to.interval === "year" ? tr("yearly") : tr("monthly") }));
    if (change.key === "seats") out.push(tr("Seats: {from} becomes {to}.", { from: seatsLabel(from, tr, locale), to: seatsLabel(to, tr, locale) }));
    if (change.key === "charge_cents")
      out.push(tr("Price: {from} becomes {to}.", { from: priceLabel(from.charge_cents, from.interval, tr, locale, from.currency), to: priceLabel(to.charge_cents, to.interval, tr, locale, to.currency) }));
    if (change.key === "ai") out.push(tr("AI included: {from} becomes {to}.", { from: aiLabel(from.ai, tr, locale), to: aiLabel(to.ai, tr, locale) }));
    if (change.key === "seat_cap")
      out.push(
        to.seat_cap === null
          ? tr("People: no fixed limit. You pay for each seat you add.")
          : tr("People: up to {n}. New invites stop there, and we never charge for extra people.",{ n: formatNumber(to.seat_cap, locale) })
      );
  }
  return out;
}

/** The interface locale as an Intl locale (Arabic uses Egyptian formatting). */
export function intlLocale(locale: string): string {
  return locale === "ar" ? "ar-EG" : locale === "pt" ? "pt-BR" : locale;
}
