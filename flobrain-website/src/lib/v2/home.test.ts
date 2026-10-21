import { describe, expect, it } from "vitest";

import { safeNext } from "./home";

describe("safeNext", () => {
  it("keeps workspace paths only", () => {
    expect(safeNext("/w/acme/tasks?x=1")).toBe("/w/acme/tasks?x=1");
    for (const bad of ["https://evil.com/w/x", "//evil.com", "/w/..//evil.com", "/w/%2e%2e//evil.com", "/w/../\t/evil.com", "/w\\evil", "/dashboard", null]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});
