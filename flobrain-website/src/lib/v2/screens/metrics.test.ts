import { describe, expect, it } from "vitest";

import { impactScoreLabel } from "./metrics";

describe("undefined metrics", () => {
  it("shows Not configured when impact score has no formula", () => {
    expect(impactScoreLabel(null)).toBe("Not configured");
    expect(impactScoreLabel(undefined)).toBe("Not configured");
    expect(impactScoreLabel(Number.NaN)).toBe("Not configured");
    expect(impactScoreLabel(12)).toBe("12");
  });
});
