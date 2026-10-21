import { describe, expect, it } from "vitest";

import { CALCULATOR_PLANS, PRICE_BOOK, calculate, cost, formatMoney, perMonth, unitPrices, yearlySavingPct, type Interval } from "./pricing";

/** Same vectors as flobrain-core/backend/billing_v2/test_pricing.py (VECTORS). */
const VECTORS: [number, Interval, number, number, number | null, number | null, string][] = [
  [1, "month", 1200, 14400, 19900, 238800, "fleet"],
  [10, "month", 12000, 144000, 19900, 238800, "fleet"],
  [16, "month", 19200, 230400, 19900, 238800, "fleet"],
  [17, "month", 20400, 244800, 19900, 238800, "studio"],
  [25, "month", 30000, 360000, 19900, 238800, "studio"],
  [26, "month", 31200, 374400, null, null, "fleet"],
  [1, "year", 1000, 12000, 16500, 198000, "fleet"],
  [16, "year", 16000, 192000, 16500, 198000, "fleet"],
  [17, "year", 17000, 204000, 16500, 198000, "studio"],
  [25, "year", 25000, 300000, 16500, 198000, "studio"],
  [26, "year", 26000, 312000, null, null, "fleet"],
];

describe("pricing math (matches the backend)", () => {
  it.each(VECTORS)("team %i, %s", (team, interval, fm, fy, sm, sy, cheaper) => {
    const out = calculate(CALCULATOR_PLANS, team, interval);
    const rows = Object.fromEntries(out.plans.map((r) => [r.code, r]));
    expect([rows.fleet.perMonthCents, rows.fleet.perYearCents]).toEqual([fm, fy]);
    expect([rows.studio.perMonthCents, rows.studio.perYearCents]).toEqual([sm, sy]);
    expect(out.cheaper).toBe(cheaper);
  });

  it("handles the edge at the cap and the break-even size", () => {
    const atCap = calculate(CALCULATOR_PLANS, 25, "month");
    expect(atCap.plans[1].available).toBe(true);
    expect(atCap.comparisons[0].breakEven).toBe(17);
    const over = calculate(CALCULATOR_PLANS, 26, "month");
    expect(over.plans[1]).toMatchObject({ available: false, reason: "over_cap" });
    expect(over.comparisons[0].savingsPerYearCents).toBe(0);
    expect(calculate(CALCULATOR_PLANS, 17, "month").comparisons[0].savingsPerYearCents).toBe(244800 - 238800);
    expect(calculate(CALCULATOR_PLANS, 3, "year").comparisons[0].breakEven).toBe(17);
  });

  it("derives yearly prices and rounds per month half up", () => {
    expect(unitPrices({ ...PRICE_BOOK.studio, yearCents: null })).toEqual({ month: 19900, year: 238800 });
    expect(perMonth(198000)).toBe(16500);
    expect(perMonth(100)).toBe(8);
    expect(perMonth(102)).toBe(9);
    expect(cost(PRICE_BOOK.crew, 11, "month").reason).toBe("over_cap");
    expect(yearlySavingPct(PRICE_BOOK.fleet)).toBe(17);
  });

  it("formats money per locale, Arabic included", () => {
    expect(formatMoney(19900, "en-US")).toBe("$199");
    expect(formatMoney(1250, "en-US")).toBe("$12.50");
    const ar = formatMoney(19900, "ar-EG");
    expect(ar).toMatch(/[٠-٩]/);
    expect(ar).not.toBe("$199");
  });
});
