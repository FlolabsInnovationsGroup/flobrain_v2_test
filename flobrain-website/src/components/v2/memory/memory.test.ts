import { describe, expect, it } from "vitest";

import { filterItems, retentionLabel, sourceLabel, splitByStatus, textProblem, type MemoryItem } from "./types";

const tr = (text: string, vars?: Record<string, string | number>) => text.replace(/\{(\w+)\}/g, (_, k: string) => String(vars?.[k] ?? `{${k}}`));

function item(id: string, text: string, extra: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id,
    scope: "person",
    text,
    category: "preference",
    source: "buddy",
    confirmed: false,
    pinned: false,
    status: "active",
    buddy: null,
    team: null,
    created_at: `2026-10-0${id}T10:00:00Z`,
    updated_at: null,
    last_used_at: null,
    expires_at: null,
    ...extra,
  };
}

describe("memory helpers", () => {
  const items = [
    item("1", "Prefers short answers"),
    item("2", "Leads the Android launch", { category: "project" }),
    item("3", "Prefers Kotlin examples", { pinned: true }),
    item("4", "Works with Sara on screenshots", { category: "people", status: "pending" }),
  ];

  it("searches every word in any order, ignoring case", () => {
    expect(filterItems(items, "android LEADS", "").map((i) => i.id)).toEqual(["2"]);
    expect(filterItems(items, "prefers", "").map((i) => i.id)).toEqual(["3", "1"]);
    expect(filterItems(items, "nothing here", "")).toEqual([]);
  });

  it("filters by category and keeps pinned first, then newest", () => {
    expect(filterItems(items, "", "preference").map((i) => i.id)).toEqual(["3", "1"]);
    expect(filterItems(items, "", "").map((i) => i.id)).toEqual(["3", "4", "2", "1"]);
  });

  it("splits suggestions from saved memories", () => {
    const { active, pending } = splitByStatus(items);
    expect(active.map((i) => i.id)).toEqual(["1", "2", "3"]);
    expect(pending.map((i) => i.id)).toEqual(["4"]);
  });

  it("checks text length", () => {
    expect(textProblem(tr, "  ")).toBe("Write the fact to remember.");
    expect(textProblem(tr, "x".repeat(301))).toBe("Keep it under 300 characters.");
    expect(textProblem(tr, "Prefers tables")).toBe("");
  });

  it("says where a memory came from", () => {
    expect(sourceLabel(tr, { source: "manual", buddy: null, confirmed: true })).toBe("You added this");
    expect(sourceLabel(tr, { source: "buddy", buddy: { id: "b", name: "Space" }, confirmed: true })).toBe("Space suggested it, you said yes");
    expect(sourceLabel(tr, { source: "buddy", buddy: null, confirmed: false })).toBe("A buddy saved it from a chat");
  });

  it("describes retention in plain words", () => {
    expect(retentionLabel(tr, null)).toBe("Kept until someone deletes it");
    expect(retentionLabel(tr, 180)).toBe("Deleted after 6 month(s)");
    expect(retentionLabel(tr, 365)).toBe("Deleted after 1 year(s)");
    expect(retentionLabel(tr, 45)).toBe("Deleted after 45 day(s)");
  });
});
