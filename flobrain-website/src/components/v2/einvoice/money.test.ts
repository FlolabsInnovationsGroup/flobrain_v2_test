import { describe, expect, it } from "vitest";

import { format, parse, round, totals } from "./money";
import { statusTone } from "./status";
import type { Line } from "./types";

const line = (over: Partial<Line>): Line => ({ description: "x", quantity: "1", unit_price: "0", discount: "0", vat_category: "S", vat_rate: "15", ...over });

describe("e-invoice live totals (same numbers as the server)", () => {
  it("parses and rounds half up exactly", () => {
    expect(parse("abc")).toBeNull();
    expect(format(round(parse("0.105")!, 2), 2)).toBe("0.11");
    expect(format(round(parse("2.005")!, 2), 2)).toBe("2.01");
    expect(format(parse("1000")!, 5)).toBe("1000.00000");
  });

  it("Saudi: line and category rounding", () => {
    const t = totals("SA", [line({ quantity: "3", unit_price: "33.33", discount: "1" })]);
    expect(format(t.lines[0]!.net, 2)).toBe("98.99");
    expect(format(t.lines[0]!.vat, 2)).toBe("14.85");
    expect(format(t.total, 2)).toBe("113.84");
    // VAT per category, rounded once: 3 x 0.10 at 15% = 0.045 -> 0.05 (not 3 x 0.02)
    const c = totals("SA", [line({ unit_price: "0.10" }), line({ unit_price: "0.10" }), line({ unit_price: "0.10" })]);
    expect(format(c.vat, 2)).toBe("0.05");
    expect(format(c.total, 2)).toBe("0.35");
  });

  it("Egypt: 5 decimals and exchange rate", () => {
    const t = totals("EG", [line({ quantity: "3", unit_price: "333.33333", discount: "10", vat_category: "V009", vat_rate: "14" })]);
    expect(format(t.vat, 5)).toBe("138.60000");
    expect(format(t.total, 5)).toBe("1128.59999");
    const fx = totals("EG", [line({ quantity: "2", unit_price: "100", vat_category: "V009", vat_rate: "14" })], "48.12345");
    expect(format(fx.net, 5)).toBe("9624.69000");
    expect(format(fx.vat, 5)).toBe("1347.45660");
  });

  it("flags invalid lines", () => {
    expect(totals("SA", [line({ unit_price: "abc" })]).valid).toBe(false);
    expect(totals("SA", [line({ unit_price: "10", discount: "11" })]).valid).toBe(false);
    expect(totals("SA", []).valid).toBe(false);
  });

  it("uses one colour per meaning", () => {
    expect(statusTone("ready", true)).toBe("waiting");
    expect(statusTone("accepted", false)).toBe("good");
    expect(statusTone("rejected", false)).toBe("bad");
    expect(statusTone("error", false)).toBe("bad");
    expect(statusTone("draft", false)).toBe("neutral");
  });
});

describe("display", () => {
  it("shows 2 decimals and keeps real precision", async () => {
    const { display } = await import("./money");
    expect(display("2736.00000")).toBe("2736.00");
    expect(display("12.34567")).toBe("12.34567");
    expect(display("10.5")).toBe("10.50");
    expect(display("7")).toBe("7.00");
    expect(display("-3.10000")).toBe("-3.10");
  });
});
