import { describe, expect, it } from "vitest";

import { navFor, roleLabel, type Access } from "./access";

function access(over: Partial<Access>): Access {
  return {
    org: { id: "o", slug: "demo", name: "Demo", demo: true },
    user_id: "u",
    org_role: "member",
    is_platform_admin: false,
    leads_teams: [],
    permissions: ["ai.use", "knowledge.ask", "content.use", "org.view"],
    flags: { buddies: true, memory_search: true, ai_actions: true, content_studio: true, auto_reports: true },
    demo_role: null,
    ...over,
  };
}

const labels = (a: Access) => navFor("demo", a).flatMap((g) => g.items.map((i) => i.label));

describe("navFor", () => {
  it("shows a member only what they can use", () => {
    const items = labels(access({}));
    expect(items).toContain("nav.ask");
    expect(items).toContain("nav.approvals");
    expect(items).not.toContain("nav.reports");
    expect(items).not.toContain("nav.billing");
    expect(items).not.toContain("nav.export");
    expect(items).not.toContain("nav.console");
  });

  it("hides features whose flag is off", () => {
    const items = labels(access({ flags: {} }));
    expect(items).not.toContain("nav.ask");
    expect(items).not.toContain("nav.studio");
  });

  it("gives leads reports and owners the owner pages", () => {
    expect(labels(access({ leads_teams: ["t1"] }))).toContain("nav.reports");
    const owner = labels(access({ org_role: "owner", permissions: ["billing.view", "sso.manage", "exports.memory", "policy.manage"] }));
    expect(owner).toEqual(expect.arrayContaining(["nav.billing", "nav.sso", "nav.export", "nav.aiPolicy"]));
  });

  it("adds the demo tour and labels roles", () => {
    expect(labels(access({ demo_role: "member" }))).toContain("nav.tour");
    expect(roleLabel(access({ leads_teams: ["t"] }))).toBe("Team lead");
    expect(roleLabel(access({ org_role: "owner" }))).toBe("Owner");
  });
});
