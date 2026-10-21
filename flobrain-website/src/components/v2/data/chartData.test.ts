import { describe, expect, it } from "vitest";

import { buildChart, formatValue, headlineValue, humanize, OTHER, toNumber } from "./chartData";

const result = {
  columns: ["week", "channel", "signups"],
  rows: [
    ["2026-10-05", "Website", 40],
    ["2026-10-05", "Referral", 12],
    ["2026-10-05", "Events", 3],
    ["2026-10-05", "Social", 9],
    ["2026-10-12", "Website", 45],
    ["2026-10-12", "Referral", 15],
    ["2026-10-12", "Events", 4],
  ],
};

describe("buildChart", () => {
  it("keeps one key per y column without a series", () => {
    const out = buildChart({ type: "bar", x: "channel", y: ["signups"], series: null }, result);
    expect(out.series).toEqual([{ key: "s0", label: "signups", slot: 0 }]);
    expect(out.data[0]).toEqual({ x: "Website", s0: 40 });
  });

  it("pivots a series column and folds the smallest into Other", () => {
    const out = buildChart({ type: "line", x: "week", y: ["signups"], series: "channel" }, result);
    expect(out.series.map((s) => s.label)).toEqual(["Referral", "Website", "Other"]);
    expect(out.folded).toBe(2);
    expect(out.data).toEqual([
      { x: "2026-10-05", s0: 12, s1: 40, [OTHER]: 12 },
      { x: "2026-10-12", s0: 15, s1: 45, [OTHER]: 4 },
    ]);
  });

  it("colors follow names, not ranks", () => {
    const small = { columns: result.columns, rows: result.rows.filter((r) => r[1] !== "Social" && r[1] !== "Events") };
    const a = buildChart({ type: "bar", x: "week", y: ["signups"], series: "channel" }, small);
    const swapped = { columns: small.columns, rows: small.rows.map((r) => (r[1] === "Referral" ? [r[0], r[1], 999] : r)) };
    const b = buildChart({ type: "bar", x: "week", y: ["signups"], series: "channel" }, swapped);
    expect(a.series).toEqual(b.series);
  });

  it("returns nothing for tables or unknown columns", () => {
    expect(buildChart({ type: "table", x: null, y: [], series: null }, result).data).toEqual([]);
    expect(buildChart({ type: "bar", x: "nope", y: ["signups"], series: null }, result).data).toEqual([]);
    expect(buildChart({ type: "bar", x: "week", y: ["nope"], series: null }, result).data).toEqual([]);
  });

  it("caps plain y columns at three", () => {
    const wide = { columns: ["c", "a", "b", "d", "e"], rows: [["x", 1, 2, 3, 4]] };
    const out = buildChart({ type: "bar", x: "c", y: ["a", "b", "d", "e"], series: null }, wide);
    expect(out.series.length).toBe(3);
    expect(out.folded).toBe(1);
  });
});

describe("helpers", () => {
  it("reads numbers and headline values", () => {
    expect(toNumber("12.5")).toBe(12.5);
    expect(toNumber("")).toBeNull();
    expect(toNumber("abc")).toBeNull();
    expect(headlineValue({ type: "number", x: null, y: ["total"], series: null }, { columns: ["total"], rows: [[42]] })).toBe(42);
    expect(headlineValue({ type: "number", x: null, y: ["total"], series: null }, { columns: ["total"], rows: [] })).toBeNull();
  });

  it("formats and humanizes", () => {
    expect(formatValue(1234.567, "en")).toBe("1,234.57");
    expect(formatValue(15300, "en", true)).toBe("15.3K");
    expect(formatValue("Web", "en")).toBe("Web");
    expect(humanize("budget_left")).toBe("Budget left");
  });
});
