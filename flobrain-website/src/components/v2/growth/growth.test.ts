import { describe, expect, it } from "vitest";

import { barPercent, firstOpen, groupPreview, localized, meterState, starFill, workspaceHref, type LessonSummary, type PackItem } from "./growth";

const lesson = (key: string, completed: boolean): LessonSummary => ({
  key,
  title: key,
  summary: "",
  minutes: 3,
  feature: null,
  try_it: { label: "Go", path: "/ask" },
  questions: 2,
  progress: { read: true, tried: false, attempts: 0, best_score: 0, completed, completed_at: null },
});

describe("growth helpers", () => {
  it("picks Arabic only when the interface is Arabic and a translation exists", () => {
    expect(localized("ar", "Hello", "مرحبا")).toBe("مرحبا");
    expect(localized("ar", "Hello", "")).toBe("Hello");
    expect(localized("fr", "Hello", "مرحبا")).toBe("Hello");
  });

  it("clamps bar widths", () => {
    expect(barPercent(50, 200)).toBe(25);
    expect(barPercent(500, 200)).toBe(100);
    expect(barPercent(-3, 200)).toBe(0);
    expect(barPercent(10, 0)).toBe(0);
    expect(barPercent(Number.NaN, 10)).toBe(0);
  });

  it("reports the meter state", () => {
    expect(meterState({ used: 10, included_total: 100, projected: 50 })).toBe("ok");
    expect(meterState({ used: 60, included_total: 100, projected: 140 })).toBe("trending");
    expect(meterState({ used: 101, included_total: 100, projected: 300 })).toBe("over");
    expect(meterState({ used: 5, included_total: 0, projected: 50 })).toBe("ok");
  });

  it("fills whole stars", () => {
    expect(starFill(4.4)).toEqual([true, true, true, true, false]);
    expect(starFill(4.5)).toEqual([true, true, true, true, true]);
    expect(starFill(null)).toEqual([false, false, false, false, false]);
  });

  it("groups a pack preview", () => {
    const item = (key: string, action: PackItem["action"]): PackItem => ({ key, kind: "room", label: key, detail: "", action, needs: "" });
    const groups = groupPreview([item("a", "create"), item("b", "skip"), item("c", "installed"), item("d", "removed")]);
    expect(groups.create.map((i) => i.key)).toEqual(["a"]);
    expect(groups.skip.map((i) => i.key)).toEqual(["b"]);
    expect(groups.installed.map((i) => i.key)).toEqual(["c", "d"]);
  });

  it("only links lessons inside the workspace", () => {
    expect(workspaceHref("acme", "/settings/profile")).toBe("/w/acme/settings/profile");
    expect(workspaceHref("acme", "https://evil.example")).toBe("/w/acme");
    expect(workspaceHref("acme", "//evil.example")).toBe("/w/acme");
    expect(workspaceHref("acme", "//evil")).toBe("/w/acme");
    expect(workspaceHref("acme", "javascript:alert(1)")).toBe("/w/acme");
  });

  it("opens the first lesson not done", () => {
    expect(firstOpen([lesson("a", true), lesson("b", false), lesson("c", false)])?.key).toBe("b");
    expect(firstOpen([lesson("a", true)])).toBeNull();
  });
});
