import { describe, expect, it } from "vitest";

import { canViewMemberProfile, profileHeadline } from "./memberProfile";

describe("member profile logic", () => {
  it("hides pending members from non-managers", () => {
    const pending = { id: "p", username: "Pat", employment_status: "pending" };
    expect(canViewMemberProfile(pending, false)).toBe(false);
    expect(canViewMemberProfile(pending, true)).toBe(true);
    expect(canViewMemberProfile(null, true)).toBe(false);
  });

  it("prefers username for the headline", () => {
    expect(profileHeadline({ id: "1", username: "Ada", email: "ada@org.test" })).toBe("Ada");
  });
});
