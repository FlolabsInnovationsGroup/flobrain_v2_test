/**
 * The one frontend place for plan prices, and the price math shared by the V2 site (/v2/pricing)
 * and the workspace billing page.
 *
 * SAMPLE PRICES. Nothing here is decided (docs/v2/DECISIONS_NEEDED.md Q22). Every screen that shows
 * a number from this file must say it is a sample (`PRICES_ARE_SAMPLE`).
 *
 * The math mirrors flobrain-core/backend/billing_v2/pricing.py exactly (same rules, same rounding).
 * The server's numbers live in Plan rows (seeded from billing_v2/sample_plans.py). `pricing.test.ts`
 * and `billing_v2/test_pricing.py` check the same team sizes against the same cents.
 */

export const PRICES_ARE_SAMPLE = true;
export const CURRENCY = "USD";
export const MAX_TEAM = 10000;

export type Interval = "month" | "year";
export type BillingUnit = "per_seat" | "per_workspace";

export type PricePlan = {
  code: string;
  name: string;
  billingUnit: BillingUnit;
  /** Cents per seat (per_seat) or for the whole workspace (per_workspace), billed monthly. */
  monthCents: number | null;
  /** Cents per seat or per workspace for a year; null = 12 x monthly. */
  yearCents: number | null;
  /** Per seat: most people allowed (null = no cap). Per workspace: people included for one price. */
  seatCap: number | null;
  /** Plans with the same tier have the same features; the calculator compares within a tier. */
  tier: string;
  /** Buddy answers included each month: per seat, or for the whole workspace. */
  aiPerSeat: number | null;
  aiPerWorkspace: number | null;
};

/** Sample price book (cents). Keep in step with billing_v2/sample_plans.py and growth/allowance.py. */
export const PRICE_BOOK: Record<"crew" | "fleet" | "studio", PricePlan> = {
  crew: { code: "crew", name: "Crew", billingUnit: "per_seat", monthCents: 0, yearCents: 0, seatCap: 10, tier: "crew", aiPerSeat: 500, aiPerWorkspace: null },
  fleet: { code: "fleet", name: "Fleet", billingUnit: "per_seat", monthCents: 1200, yearCents: 12000, seatCap: null, tier: "fleet", aiPerSeat: 1500, aiPerWorkspace: null },
  studio: { code: "studio", name: "Studio", billingUnit: "per_workspace", monthCents: 19900, yearCents: 198000, seatCap: 25, tier: "fleet", aiPerSeat: null, aiPerWorkspace: 30000 },
};

/** The two plans the team-size slider compares. */
export const CALCULATOR_PLANS: PricePlan[] = [PRICE_BOOK.fleet, PRICE_BOOK.studio];

export type CostRow = {
  code: string;
  name: string;
  billingUnit: BillingUnit;
  available: boolean;
  reason: "" | "over_cap" | "interval_not_offered";
  unitPriceCents: number | null;
  perMonthCents: number | null;
  perYearCents: number | null;
  seatCap: number | null;
};

export type Comparison = {
  tier: string;
  perSeat: string;
  perWorkspace: string;
  cheaper: string | null;
  cheaperUnit: BillingUnit | null;
  savingsPerYearCents: number;
  breakEven: number | null;
};

export type Calculation = { teamSize: number; interval: Interval; plans: CostRow[]; comparisons: Comparison[]; cheaper: string | null; cheaperUnit: BillingUnit | null };

export function unitPrices(plan: PricePlan): Record<Interval, number | null> {
  if (plan.monthCents === null) return { month: null, year: plan.yearCents };
  return { month: plan.monthCents, year: plan.yearCents || plan.monthCents * 12 };
}

/** A yearly total shown per month: / 12, rounded half up to a whole cent (same as the server). */
export function perMonth(yearCents: number): number {
  return Math.floor((yearCents + 6) / 12);
}

export function cost(plan: PricePlan, team: number, interval: Interval): CostRow {
  const price = unitPrices(plan)[interval];
  const row: CostRow = {
    code: plan.code,
    name: plan.name,
    billingUnit: plan.billingUnit,
    available: true,
    reason: "",
    unitPriceCents: price,
    perMonthCents: null,
    perYearCents: null,
    seatCap: plan.seatCap,
  };
  if (price === null) return { ...row, available: false, reason: "interval_not_offered" };
  if (plan.seatCap !== null && team > plan.seatCap) return { ...row, available: false, reason: "over_cap" };
  const total = plan.billingUnit === "per_workspace" ? price : price * team;
  return interval === "month" ? { ...row, perMonthCents: total, perYearCents: total * 12 } : { ...row, perMonthCents: perMonth(total), perYearCents: total };
}

/** Smallest team where the workspace price beats per seat, or null (never, or only above the cap). */
export function breakEven(seat: CostRow, space: CostRow): number | null {
  if (!seat.unitPriceCents || !space.unitPriceCents) return null;
  const n = Math.floor(space.unitPriceCents / seat.unitPriceCents) + 1;
  return space.seatCap !== null && n > space.seatCap ? null : n;
}

export function calculate(plans: PricePlan[], team: number, interval: Interval): Calculation {
  const rows = plans.map((p) => cost(p, team, interval));
  const tiers = [...new Set(plans.map((p) => p.tier || p.code))];
  const comparisons: Comparison[] = [];
  for (const tier of tiers) {
    const paid = rows.filter((r, i) => (plans[i].tier || plans[i].code) === tier && (r.unitPriceCents ?? 0) > 0);
    const seat = paid.find((r) => r.billingUnit === "per_seat");
    const space = paid.find((r) => r.billingUnit === "per_workspace");
    if (!seat || !space) continue;
    const options = [seat, space].filter((r) => r.available);
    let cheaper: CostRow | null = null;
    let savings = 0;
    if (options.length === 1) cheaper = options[0];
    else if (options.length === 2) {
      cheaper = (space.perYearCents as number) < (seat.perYearCents as number) ? space : seat;
      const other = cheaper === space ? seat : space;
      savings = (other.perYearCents as number) - (cheaper.perYearCents as number);
    }
    comparisons.push({
      tier,
      perSeat: seat.code,
      perWorkspace: space.code,
      cheaper: cheaper?.code ?? null,
      cheaperUnit: cheaper?.billingUnit ?? null,
      savingsPerYearCents: savings,
      breakEven: breakEven(seat, space),
    });
  }
  const first = comparisons[0];
  return { teamSize: team, interval, plans: rows, comparisons, cheaper: first?.cheaper ?? null, cheaperUnit: first?.cheaperUnit ?? null };
}

/** Yearly discount against 12 x monthly, in whole percent (for the "Save" tag). */
export function yearlySavingPct(plan: PricePlan): number {
  const p = unitPrices(plan);
  if (!p.month || p.year === null) return 0;
  return Math.round((100 * (p.month * 12 - p.year)) / (p.month * 12));
}

/** Money for any locale, Arabic included. Whole amounts drop the cents. */
export function formatMoney(cents: number, locale?: string, currency = CURRENCY): string {
  const value = cents / 100;
  const whole = Number.isInteger(value);
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency, minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(whole ? 0 : 2)} ${currency}`;
  }
}

export function formatNumber(n: number, locale?: string): string {
  try {
    return new Intl.NumberFormat(locale).format(n);
  } catch {
    return String(n);
  }
}
