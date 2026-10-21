import { describe, expect, it } from "vitest";

import { sumEntrySeconds, weeklyTotalMatchesEntries } from "./reports";

describe("reports logic", () => {
  it("matches weekly totals to the sum of entries", () => {
    const entries = [{ seconds: 3600 }, { seconds: 1800 }];
    expect(sumEntrySeconds(entries)).toBe(5400);
    expect(weeklyTotalMatchesEntries({ seconds: 5400 }, entries)).toBe(true);
    expect(weeklyTotalMatchesEntries({ seconds: 1 }, entries)).toBe(false);
  });
});
