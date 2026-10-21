import { describe, expect, it } from "vitest";

import {
  auditQuery,
  browserLabel,
  EMPTY_FILTERS,
  grantState,
  memberQuery,
  normalizePhone,
  pageCount,
  requestable,
  scopesFor,
  screenFor,
  statusTone,
} from "./people";

describe("directory query", () => {
  it("leaves out empty filters and keeps the page", () => {
    expect(memberQuery(EMPTY_FILTERS)).toEqual({ ordering: "name", page: "1" });
    expect(memberQuery({ q: " mona ", status: "on_leave", team: "t1", role: "lead", skill: " Python ", page: 3 })).toEqual({
      ordering: "name",
      page: "3",
      q: "mona",
      status: "on_leave",
      team: "t1",
      role: "lead",
      skill: "Python",
    });
    expect(pageCount(0)).toBe(1);
    expect(pageCount(41)).toBe(3);
    expect(statusTone("terminated")).toBe("bad");
  });
});

describe("phone", () => {
  it("matches the backend rule", () => {
    expect(normalizePhone("+20 100 123-4567")).toBe("+201001234567");
    expect(normalizePhone("0044 (20) 7946 0958")).toBe("+442079460958");
    expect(normalizePhone("0100 123 4567")).toBeNull();
    expect(normalizePhone("+12")).toBeNull();
  });
});

describe("grants and requests", () => {
  const base = { id: "g", perm_key: "audit.view", scope_type: "org", revoked_at: null, created_at: "2026-10-01T00:00:00Z" };
  const now = Date.parse("2026-10-21T00:00:00Z");
  it("names the state", () => {
    expect(grantState({ ...base, expires_at: null }, now)).toBe("active");
    expect(grantState({ ...base, expires_at: "2026-10-22T00:00:00Z" }, now)).toBe("expiring");
    expect(grantState({ ...base, expires_at: "2026-11-22T00:00:00Z" }, now)).toBe("active");
    expect(grantState({ ...base, expires_at: "2026-10-20T00:00:00Z" }, now)).toBe("expired");
    expect(grantState({ ...base, expires_at: null, revoked_at: "2026-10-02T00:00:00Z" }, now)).toBe("revoked");
  });
  it("offers only what you don't hold and can be granted", () => {
    const catalog = [
      { key: "audit.view", label: "View audit events", matrix: "org" },
      { key: "task.view", label: "View tasks", matrix: "team" },
      { key: "sso.manage", label: "Manage SSO", matrix: "org", grantable: false },
    ];
    expect(requestable(catalog, ["task.view"]).map((r) => r.key)).toEqual(["audit.view"]);
    expect(scopesFor(catalog[1])).toEqual(["org", "team"]);
    expect(scopesFor(undefined)).toEqual(["org"]);
  });
});

describe("analytics screen names", () => {
  it("strips the org, ids and query strings, and skips untracked pages", () => {
    expect(screenFor("/w/demo", "demo")).toBe("/home");
    expect(screenFor("/w/demo/rooms/0b6f0b9e-1c2d-4e5f-8a9b-0c1d2e3f4a5b/docs", "demo")).toBe("/rooms/:id/docs");
    expect(screenFor("/w/demo/tasks/", "demo")).toBe("/tasks");
    expect(screenFor("/w/demo/settings/billing", "demo")).toBeNull();
    expect(screenFor("/w/other/tasks", "demo")).toBeNull();
    expect(screenFor("/w/demo-2/tasks", "demo")).toBeNull();
  });
});

describe("audit and feedback helpers", () => {
  it("builds audit filters and a short browser label", () => {
    expect(auditQuery({ actor: "", action: " perm ", since: "2026-10-01", until: "soon", page: 2 })).toEqual({ page: "2", action: "perm", since: "2026-10-01" });
    expect(browserLabel("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0")).toBe("Firefox 140");
    expect(browserLabel("Mozilla/5.0 AppleWebKit/537.36 Chrome/141.0.0.0 Safari/537.36 Edg/141.0")).toBe("Edge 141");
    expect(browserLabel("curl")).toBe("Other browser");
  });
});
