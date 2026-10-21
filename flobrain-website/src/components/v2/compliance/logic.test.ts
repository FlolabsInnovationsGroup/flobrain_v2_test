import { describe, expect, it } from "vitest";

import {
  canChange,
  clampPct,
  cleanSubprocessors,
  filterControls,
  formatBytes,
  groupsOf,
  isoDaysAgo,
  nextPending,
  removeAt,
  reviewKey,
  statusTone,
  toggle,
  updateAt,
} from "./logic";
import type { Control } from "./types";

const control = (over: Partial<Control>): Control => ({
  framework: "iso27001",
  id: "5.1",
  group: "5",
  group_name: "Organizational",
  name: "Policies for information security",
  summary: "Policy is defined.",
  checks: [],
  status: "manual",
  source: "none",
  check_results: [],
  attestation: null,
  ...over,
});

describe("compliance logic", () => {
  it("never uses amber for control status", () => {
    expect(statusTone("pass")).toBe("good");
    expect(statusTone("fail")).toBe("bad");
    expect(statusTone("manual")).toBe("neutral");
    expect(statusTone("not_applicable")).toBe("neutral");
  });

  it("filters controls by framework, status, group and text", () => {
    const rows = [
      control({}),
      control({ id: "8.24", group: "8", group_name: "Technological", name: "Use of cryptography", status: "pass" }),
      control({ framework: "soc2", id: "CC6.1", group: "CC6", group_name: "Logical and physical access", name: "Logical access security", status: "fail" }),
    ];
    expect(filterControls(rows, { framework: "iso27001", status: "", group: "", q: "" })).toHaveLength(2);
    expect(filterControls(rows, { framework: "", status: "fail", group: "", q: "" }).map((c) => c.id)).toEqual(["CC6.1"]);
    expect(filterControls(rows, { framework: "", status: "", group: "8", q: "" }).map((c) => c.id)).toEqual(["8.24"]);
    expect(filterControls(rows, { framework: "", status: "", group: "", q: "CRYPTO" }).map((c) => c.id)).toEqual(["8.24"]);
    expect(groupsOf(rows, "iso27001")).toEqual([
      { key: "5", name: "Organizational" },
      { key: "8", name: "Technological" },
    ]);
  });

  it("maps review shortcuts and ignores typing", () => {
    expect(reviewKey({ key: "j" }, 0, 3)).toEqual({ type: "move", index: 1 });
    expect(reviewKey({ key: "ArrowDown" }, 2, 3)).toEqual({ type: "move", index: 2 });
    expect(reviewKey({ key: "k" }, 0, 3)).toEqual({ type: "move", index: 0 });
    expect(reviewKey({ key: "1" }, 0, 3)).toEqual({ type: "decide", decision: "keep" });
    expect(reviewKey({ key: "2" }, 0, 3)).toEqual({ type: "decide", decision: "revoke" });
    expect(reviewKey({ key: "3" }, 0, 3)).toEqual({ type: "decide", decision: "change" });
    expect(reviewKey({ key: "?" }, 0, 3)).toEqual({ type: "help" });
    expect(reviewKey({ key: "1", target: { tagName: "TEXTAREA" } }, 0, 3)).toBeNull();
    expect(reviewKey({ key: "1", ctrlKey: true }, 0, 3)).toBeNull();
    expect(reviewKey({ key: "j" }, 0, 0)).toBeNull();
    expect(reviewKey({ key: "x" }, 0, 3)).toBeNull();
  });

  it("finds the next item to decide, wrapping around", () => {
    const items = [
      { decision: "keep" as const, can_decide: true },
      { decision: "pending" as const, can_decide: false },
      { decision: "pending" as const, can_decide: true },
      { decision: "revoke" as const, can_decide: true },
    ];
    expect(nextPending(items, 0)).toBe(2);
    expect(nextPending(items, 2)).toBe(2);
    expect(nextPending(items, 3)).toBe(2);
  });

  it("allows change only where the server does", () => {
    expect(canChange({ kind: "grant", details: {} })).toBe(true);
    expect(canChange({ kind: "membership", details: { org_role: "admin" } })).toBe(true);
    expect(canChange({ kind: "membership", details: { org_role: "owner" } })).toBe(false);
    expect(canChange({ kind: "integration", details: {} })).toBe(false);
  });

  it("small helpers", () => {
    expect(clampPct(140)).toBe(100);
    expect(clampPct(Number.NaN)).toBe(0);
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(4_812_331)).toBe("4.6 MB");
    expect(updateAt([{ a: 1 }, { a: 2 }], 1, { a: 3 })).toEqual([{ a: 1 }, { a: 3 }]);
    expect(removeAt([1, 2, 3], 0)).toEqual([2, 3]);
    expect(toggle(["a", "c"], "b", ["a", "b", "c"])).toEqual(["a", "b", "c"]);
    expect(toggle(["a", "b"], "a", ["a", "b"])).toEqual(["b"]);
    expect(isoDaysAgo(1, new Date("2026-10-21T12:00:00Z"))).toBe("2026-10-20");
  });

  it("drops non-https websites and empty subprocessors", () => {
    expect(
      cleanSubprocessors([
        { name: " AWS ", purpose: "", location: "", website: "javascript:alert(1)" },
        { name: "", purpose: "x", location: "", website: "" },
        { name: "Stripe", purpose: "", location: "", website: "https://stripe.com" },
      ]),
    ).toEqual([
      { name: "AWS", purpose: "", location: "", website: "" },
      { name: "Stripe", purpose: "", location: "", website: "https://stripe.com" },
    ]);
  });
});
