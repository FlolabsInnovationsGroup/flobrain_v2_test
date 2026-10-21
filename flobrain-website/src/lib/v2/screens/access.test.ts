import { describe, expect, it } from "vitest";

import { accessListsEmpty, activeGrants, pendingRequests } from "./access";

describe("access settings logic", () => {
  it("keeps pending requests and active grants", () => {
    const requests = [
      { id: "1", perm_key: "audit.view", status: "pending" },
      { id: "2", perm_key: "hr.view", status: "approved" },
    ];
    const grants = [
      { id: "g1", perm_key: "audit.view", revoked_at: null },
      { id: "g2", perm_key: "hr.view", revoked_at: "2026-01-01" },
    ];
    expect(pendingRequests(requests)).toHaveLength(1);
    expect(activeGrants(grants)).toHaveLength(1);
    expect(accessListsEmpty(requests, grants)).toBe(false);
    expect(accessListsEmpty([], [])).toBe(true);
  });
});
