import { describe, expect, it } from "vitest";

import { assignFailureStatus, canAssignOther } from "./assign";

describe("assign panel logic", () => {
  it("lets leads assign only inside their team", () => {
    expect(canAssignOther("member", true)).toBe(false);
    expect(canAssignOther("lead", true)).toBe(true);
    expect(canAssignOther("lead", false)).toBe(false);
    expect(canAssignOther("owner", false)).toBe(true);
  });

  it("maps denials to 403/404", () => {
    expect(assignFailureStatus("member", true, true)).toBe(403);
    expect(assignFailureStatus("lead", false, true)).toBe(404);
    expect(assignFailureStatus("owner", true, false)).toBe(404);
  });
});
